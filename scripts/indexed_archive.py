"""Bounded reads from validated SQLite indexes; live restrictions in one transaction."""
import json
import sqlite3
import threading
from array import array
from bisect import bisect_left
from collections import OrderedDict
from contextlib import contextmanager

from archive_store import StoreError, SnapshotNotFound, connect, ensure_schema
from graph_archive import GraphUnavailable, graph_view, relation_view
from query_index import VERSION, TEXT_EDGE_CHARS, trigrams
from search_archive import fingerprint, encode_cursor, decode_cursor, ordered_passages
from validate_sample import require


_TOPOLOGY_CACHE = OrderedDict()
_TOPOLOGY_CACHE_LOCK = threading.RLock()
_TOPOLOGY_CACHE_LIMIT = 8
_SEARCH_CACHE = OrderedDict()
_SEARCH_CACHE_LIMIT = 6
_PAGE_CACHE = OrderedDict()
_PAGE_CACHE_LIMIT = 12
_TOTAL_CACHE = OrderedDict()
_TOTAL_CACHE_LIMIT = 12
# A per-connection upper bound on SQLite's read-only file mapping, not a heap
# reservation. SQLite caps/ignores this on builds without mmap and reads normally.
READ_MMAP_BYTES = 1 << 30


def text_condition(parameter):
    # Either excerpt is a contiguous substring of the normalized text. A hit
    # proves containment, but a miss proves nothing (including SQLite substr's
    # handling of NUL). Never concatenate excerpts or skip the full-body fallback.
    return f'''CASE WHEN instr(substr(v.text_norm,1,{TEXT_EDGE_CHARS}),:{parameter})>0
        OR instr(substr(v.text_norm,-{TEXT_EDGE_CHARS}),:{parameter})>0 THEN 1
        ELSE instr(v.text_norm,:{parameter})>0 END'''


def _cache_get(key):
    with _TOPOLOGY_CACHE_LOCK:
        value = _TOPOLOGY_CACHE.get(key)
        if value is not None:
            _TOPOLOGY_CACHE.move_to_end(key)
        return value


def _cache_put(key, value):
    with _TOPOLOGY_CACHE_LOCK:
        _TOPOLOGY_CACHE[key] = value
        _TOPOLOGY_CACHE.move_to_end(key)
        while len(_TOPOLOGY_CACHE) > _TOPOLOGY_CACHE_LIMIT:
            _TOPOLOGY_CACHE.popitem(last=False)
        return value


def _search_get(key):
    with _TOPOLOGY_CACHE_LOCK:
        value = _SEARCH_CACHE.get(key)
        if value is not None:
            _SEARCH_CACHE.move_to_end(key)
        return value


def _search_put(key, value):
    with _TOPOLOGY_CACHE_LOCK:
        _SEARCH_CACHE[key] = value
        _SEARCH_CACHE.move_to_end(key)
        while len(_SEARCH_CACHE) > _SEARCH_CACHE_LIMIT:
            _SEARCH_CACHE.popitem(last=False)
        return value


def _page_get(key):
    with _TOPOLOGY_CACHE_LOCK:
        value = _PAGE_CACHE.get(key)
        if value is not None:
            _PAGE_CACHE.move_to_end(key)
        return value


def _page_put(key, value):
    with _TOPOLOGY_CACHE_LOCK:
        _PAGE_CACHE[key] = value
        _PAGE_CACHE.move_to_end(key)
        while len(_PAGE_CACHE) > _PAGE_CACHE_LIMIT:
            _PAGE_CACHE.popitem(last=False)
        return value


def _total_get(key):
    with _TOPOLOGY_CACHE_LOCK:
        value = _TOTAL_CACHE.get(key)
        if value is not None:
            _TOTAL_CACHE.move_to_end(key)
        return value


def _total_put(key, value):
    with _TOPOLOGY_CACHE_LOCK:
        _TOTAL_CACHE[key] = value
        _TOTAL_CACHE.move_to_end(key)
        while len(_TOTAL_CACHE) > _TOTAL_CACHE_LIMIT:
            _TOTAL_CACHE.popitem(last=False)
        return value


@contextmanager
def indexed_view(database, snapshot, scopes, purpose):
    connection = None
    try:
        connection = connect(database)
        connection.execute(f'PRAGMA mmap_size={READ_MMAP_BYTES}')
        connection.execute('BEGIN')
        yield IndexedArchive(connection, snapshot, scopes, purpose)
    except sqlite3.Error as error:
        raise StoreError('Query index unavailable; verify and rebuild before serving.') from error
    finally:
        if connection is not None:
            connection.rollback()
            connection.close()


class IndexedArchive:
    def __init__(self, connection, snapshot, scopes, purpose):
        self.connection = connection
        ensure_schema(connection)
        if snapshot is None:
            state = connection.execute('SELECT active_snapshot_id FROM archive_state WHERE singleton=1').fetchone()
            if not state or not state[0]:
                raise StoreError('No active snapshot.')
            snapshot = state[0]
        row = connection.execute('SELECT metadata,content_hash FROM snapshots WHERE id=?', (snapshot,)).fetchone()
        if row is None:
            raise SnapshotNotFound('Snapshot unavailable.')
        self.metadata = json.loads(row['metadata'])
        require(purpose in ('display', 'export', 'external_ai'), 'unsupported purpose')
        require(set(scopes) <= set(self.metadata['scope_ids']), 'unknown scope')
        index = connection.execute('SELECT ready,content_hash,has_backlinks FROM query_snapshots WHERE snapshot_id=?', (snapshot,)).fetchone()
        state = connection.execute('SELECT version,policy_revision FROM query_state WHERE singleton=1').fetchone()
        if not index or not index['ready'] or index['content_hash'] != row['content_hash'] or not state or state['version'] != VERSION:
            raise StoreError('Unverified or stale query index; rebuild required.')
        self.snapshot = snapshot
        self.has_backlinks = bool(index['has_backlinks'])
        self._ordered = None
        self._ordered_index = None
        self._ordered_position_index = None
        self._order_adjustments = None
        self._position_adjustments = None
        self._visible_rows = None
        self._visible_ids = None
        self._visible_links = None
        self._dense_order = False
        self.scopes = sorted(set(scopes)); self.purpose = purpose
        self.mask = sum(1 << self.metadata['scope_ids'].index(scope) for scope in self.scopes)
        self.meta = {key: self.metadata[key] for key in ('dataset_kind', 'notice', 'snapshot_id')}
        self.meta.update(scope_ids=self.scopes, purpose=purpose)
        # Conservative invalidation: any restriction update invalidates continuations,
        # including old snapshots. No raw policy counts or revision are exposed.
        self.revision = fingerprint({'snapshot': row['content_hash'], 'policy': state['policy_revision'], 'index': VERSION})
        database_path = connection.execute('PRAGMA database_list').fetchone()[2]
        self.topology_cache_key = (database_path, snapshot, tuple(self.scopes), purpose, self.revision)
        self.params = {'snapshot': snapshot, 'mask': self.mask, 'purpose': purpose}
        self.cte = '''WITH allowed_sources AS MATERIALIZED (
          SELECT s.id FROM source_policies s
          WHERE json_extract(s.rights, '$.' || :purpose)='allowed'
          AND NOT EXISTS(SELECT 1 FROM withdrawals w WHERE w.id=s.id)
        ), base AS NOT MATERIALIZED (
          SELECT q.* FROM query_records q
          WHERE q.snapshot_id=:snapshot AND (q.scope_mask & :mask)=q.scope_mask
          AND q.source_id IN (SELECT id FROM allowed_sources)
          AND NOT EXISTS(SELECT 1 FROM withdrawals w WHERE w.id=q.id)
        ), people AS MATERIALIZED (SELECT * FROM base WHERE collection='characters'),
        entries AS MATERIALIZED (SELECT * FROM base WHERE collection='entries'),
        passages AS NOT MATERIALIZED (
          SELECT p.* FROM base p WHERE p.collection='passages'
          AND p.entry_id IN (SELECT id FROM entries)
          AND (p.speaker_id IS NULL OR p.speaker_id IN (SELECT id FROM people))
        ), groups AS NOT MATERIALIZED (
          SELECT e.relation_id,e.group_number FROM query_evidence e
          WHERE e.snapshot_id=:snapshot GROUP BY e.relation_id,e.group_number
          HAVING sum(CASE WHEN EXISTS(SELECT 1 FROM passages p WHERE p.id=e.passage_id) THEN 0 ELSE 1 END)=0
        ), relations AS NOT MATERIALIZED (
          SELECT r.* FROM base r WHERE r.collection='relationships' AND r.approved=1
          AND EXISTS(SELECT 1 FROM people a WHERE a.id=r.from_id)
          AND EXISTS(SELECT 1 FROM people b WHERE b.id=r.to_id)
          AND EXISTS(SELECT 1 FROM groups g WHERE g.relation_id=r.id)
        ) '''
        passages_cte = '''WITH allowed_sources AS MATERIALIZED (
          SELECT s.id FROM source_policies s
          WHERE json_extract(s.rights, '$.' || :purpose)='allowed'
          AND NOT EXISTS(SELECT 1 FROM withdrawals w WHERE w.id=s.id)
        ), people AS MATERIALIZED (
          SELECT q.id FROM query_records q{record_index} WHERE q.snapshot_id=:snapshot AND q.collection='characters'
            AND (q.scope_mask & :mask)=q.scope_mask AND q.source_id IN (SELECT id FROM allowed_sources)
            AND NOT EXISTS(SELECT 1 FROM withdrawals w WHERE w.id=q.id)
        ), entries AS MATERIALIZED (
          SELECT q.id FROM query_records q{record_index} WHERE q.snapshot_id=:snapshot AND q.collection='entries'
            AND (q.scope_mask & :mask)=q.scope_mask AND q.source_id IN (SELECT id FROM allowed_sources)
            AND NOT EXISTS(SELECT 1 FROM withdrawals w WHERE w.id=q.id)
        ), passages AS NOT MATERIALIZED (
          SELECT q.* FROM query_records q{record_index} WHERE q.snapshot_id=:snapshot AND q.collection='passages'
            AND (q.scope_mask & :mask)=q.scope_mask AND q.source_id IN (SELECT id FROM allowed_sources)
            AND NOT EXISTS(SELECT 1 FROM withdrawals w WHERE w.id=q.id)
            AND q.entry_id IN (SELECT id FROM entries)
            AND (q.speaker_id IS NULL OR q.speaker_id IN (SELECT id FROM people))
        ) '''
        self.passages_cte = passages_cte.format(record_index='')
        self.visibility_cte = passages_cte.format(record_index=' INDEXED BY query_visibility')
        self.search_cte = passages_cte.format(record_index=' INDEXED BY query_search_text')

    def rows(self, sql, parameters=None):
        return self.connection.execute(self.cte + sql, {**self.params, **(parameters or {})}).fetchall()

    def passage_rows(self, sql, parameters=None):
        return self.connection.execute(self.passages_cte + sql, {**self.params, **(parameters or {})}).fetchall()

    def search_rows(self, sql, parameters=None):
        return self.connection.execute(self.search_cte + sql, {**self.params, **(parameters or {})}).fetchall()

    def visibility_rows(self, sql, parameters=None):
        return self.connection.execute(self.visibility_cte + sql, {**self.params, **(parameters or {})}).fetchall()

    def records(self, collection, where='1', parameters=None, order='v.position', limit=None, identifiers=None):
        table = {'characters': 'people', 'entries': 'entries', 'passages': 'passages', 'relationships': 'relations'}[collection]
        if collection == 'passages' and order == 'v.sort_rank':
            identifiers = self.ordered_page(where, parameters, limit)
            payloads = {p['id']: p for p in self.selected('passages', set(identifiers))}
            return [payloads[identifier] for identifier in identifiers]
        origin = f'{table} v'
        if identifiers is not None:
            origin = f'json_each(:selected_ids) wanted CROSS JOIN {table} v ON wanted.value=v.id'
            parameters = {**(parameters or {}), 'selected_ids': json.dumps(sorted(identifiers))}
        sql = f'SELECT r.payload FROM {origin} CROSS JOIN records r ON r.snapshot_id=:snapshot AND r.id=v.id WHERE {where} ORDER BY {order}'
        if limit is not None:
            sql += ' LIMIT :take OFFSET :skip'
            parameters = {**(parameters or {}), 'take': limit[0], 'skip': limit[1]}
        result = [json.loads(row[0]) for row in self.rows(sql, parameters)]
        if collection == 'passages':
            links = self.visible_links()
            for passage in result:
                passage['next_ids'] = [identifier for identifier in passage['next_ids'] if identifier in links.get(passage['id'], ())]
        elif collection == 'relationships':
            for relation in result:
                allowed = {row[0] for row in self.rows('SELECT group_number FROM groups WHERE relation_id=:id', {'id': relation['id']})}
                relation['evidence_groups'] = [group for number, group in enumerate(relation['evidence_groups']) if number in allowed]
        return result

    def linked_order(self):
        """Merge isolated positions with the stable topology of visible linked nodes.

        Kahn's position-priority traversal emits isolated nodes before the next
        linked node's running maximum source position. Only linked nodes need
        adjusted keys; filtering a global topological rank would be incorrect.
        """
        if not self.has_backlinks:
            return {}
        if self._order_adjustments is None:
            cached = _cache_get(('linked', self.topology_cache_key))
            if cached is not None:
                self._order_adjustments, self._position_adjustments = cached
                return self._order_adjustments
            links = self.visible_links()
            nodes = {}
            linked_ids = set(links)
            linked_ids.update(identifier for values in links.values() for identifier in values)
            positions = {row['id']: row['position'] for row in self.passage_rows(
                '''SELECT v.id,v.position FROM json_each(:ids) wanted
                   CROSS JOIN passages v ON v.id=wanted.value''',
                {'ids': json.dumps(sorted(linked_ids))})}
            for from_id, following_ids in links.items():
                nodes.setdefault(from_id, {'id': from_id, 'position': positions[from_id], 'next_ids': []})['next_ids'].extend(following_ids)
                for following in following_ids:
                    nodes.setdefault(following, {'id': following, 'position': positions[following], 'next_ids': []})
            ordered = ordered_passages(sorted(nodes.values(), key=lambda p: p['position']))
            released = -1
            adjustments = {}
            for sequence, node in enumerate(ordered):
                released = max(released, node['position'])
                adjustments[node['id']] = (released, sequence)
            self._order_adjustments = adjustments
            self._position_adjustments = {positions[identifier]: key for identifier, key in adjustments.items()}
            _cache_put(('linked', self.topology_cache_key), (self._order_adjustments, self._position_adjustments))
        return self._order_adjustments

    def ordered_page(self, where, parameters, limit):
        if not self.has_backlinks and where == '1':
            sql = 'SELECT v.id FROM passages v ORDER BY v.position'
            params = dict(parameters or {})
            if limit is not None:
                sql += ' LIMIT :take OFFSET :skip'
                params.update(take=limit[0], skip=limit[1])
            return [row['id'] for row in self.passage_rows(sql, params)]
        if where == '1' and limit is not None and len(self.visible_links()) <= 5000:
            rows = self.visible_passage_rows()
            linked = self.linked_order()
            if not linked:
                return [row['id'] for row in rows[limit[1]:limit[1] + limit[0]]]
            linked_ids = set(linked)
            positions = {row['id']: row['position'] for row in rows}
            start = max(0, limit[1] - len(linked))
            ordinary = [{'id': row['id'], 'position': row['position']}
                        for row in rows if row['id'] not in linked_ids]
            ordinary = ordinary[start:start + limit[0] + len(linked)]
            linked_rows = [{'id': identifier, 'position': positions[identifier]} for identifier in linked]
            merged = sorted([*ordinary, *linked_rows], key=lambda row: linked.get(row['id'], (row['position'], -1)))
            relative = limit[1] - start
            return [row['id'] for row in merged[relative:relative + limit[0]]]
        if self.has_backlinks and len(self.visible_links()) > 5000:
            ordered = self.ordered_ids()
            if where == '1':
                return ordered[limit[1]:limit[1] + limit[0]] if limit is not None else ordered
            rows = self.passage_rows(f'SELECT v.id FROM passages v WHERE {where}', parameters)
            matching = {row['id'] for row in rows}
            identifiers = [identifier for identifier in ordered if identifier in matching]
            return identifiers[limit[1]:limit[1] + limit[0]] if limit is not None else identifiers
        linked = self.linked_order()
        if self._dense_order:
            rows = self.rows(f'SELECT v.id FROM passages v WHERE {where}', parameters)
            identifiers = sorted((row['id'] for row in rows), key=self._ordered_index.__getitem__)
            if limit is not None:
                return identifiers[limit[1]:limit[1] + limit[0]]
            return identifiers
        params = {**(parameters or {}), 'linked': json.dumps(list(linked))}
        matches = self.passage_rows(f'''SELECT v.id,v.position FROM json_each(:linked) wanted
            CROSS JOIN passages v ON v.id=wanted.value WHERE {where}''', params) if linked else []
        sql = f'SELECT v.id,v.position FROM passages v WHERE {where}'
        if linked:
            sql += ' AND v.id NOT IN (SELECT value FROM json_each(:linked))'
        sql += ' ORDER BY v.position'
        start = 0
        if limit is not None:
            # At most len(matches) linked nodes can precede this page. Everything
            # omitted from the ordinary prefix must therefore precede the page.
            start = max(0, limit[1] - len(matches))
            sql += ' LIMIT :take OFFSET :skip'
            params.update(take=limit[0] + len(matches), skip=start)
        ordinary = self.passage_rows(sql, params)
        merged = sorted([*ordinary, *matches], key=lambda row: linked.get(row['id'], (row['position'], -1)))
        if limit is not None:
            relative = limit[1] - start
            merged = merged[relative:relative + limit[0]]
        return [row['id'] for row in merged]

    def ordered_ids(self):
        # Rare out-of-order source occurrences need topology of the visible graph,
        # not a filtered global ranking. Fetch only IDs/links, never all text bodies.
        if self._ordered is None:
            cached = _cache_get(('ordered', self.topology_cache_key))
            if cached is not None:
                self._ordered, self._ordered_index, self._ordered_position_index = cached
                return self._ordered
            links = self.visible_links()
            nodes = [{'id': row['id'], 'next_ids': list(links.get(row['id'], ())) }
                     for row in self.visible_passage_rows()]
            self._ordered = [p['id'] for p in ordered_passages(nodes)]
            self._ordered_index = {identifier: rank for rank, identifier in enumerate(self._ordered)}
            self._ordered_position_index = {row['position']: self._ordered_index[row['id']]
                                            for row in self.visible_passage_rows()}
            _cache_put(('ordered', self.topology_cache_key),
                       (self._ordered, self._ordered_index, self._ordered_position_index))
        return self._ordered

    def visible_passage_rows(self):
        if self._visible_rows is None:
            cached = _cache_get(('rows', self.topology_cache_key))
            self._visible_rows = cached if cached is not None else _cache_put(
                ('rows', self.topology_cache_key), self.passage_rows('SELECT id,position FROM passages ORDER BY position'))
            self._visible_ids = {row['id'] for row in self._visible_rows}
        return self._visible_rows

    def visible_links(self):
        if self._visible_links is None:
            cached = _cache_get(('links', self.topology_cache_key))
            if cached is not None:
                self._visible_links = cached
                return cached
            pairs = self.connection.execute(
                'SELECT from_id,to_id FROM query_links WHERE snapshot_id=?', (self.snapshot,)).fetchall()
            candidates = {identifier for row in pairs for identifier in (row['from_id'], row['to_id'])}
            visible = {row['id'] for row in self.passage_rows(
                '''SELECT v.id FROM json_each(:ids) wanted
                   CROSS JOIN passages v ON v.id=wanted.value''',
                {'ids': json.dumps(sorted(candidates))})}
            links = {}
            for row in pairs:
                if row['from_id'] in visible and row['to_id'] in visible:
                    links.setdefault(row['from_id'], []).append(row['to_id'])
            self._visible_links = links
            _cache_put(('links', self.topology_cache_key), links)
        return self._visible_links

    def selected(self, collection, identifiers):
        if not identifiers:
            return []
        return self.records(collection, identifiers=identifiers)

    def passage_page(self, identifiers):
        """Hydrate a known page without re-running the full archive CTE."""
        if not identifiers:
            return []
        sql = '''SELECT r.payload FROM json_each(:selected_ids) wanted
            CROSS JOIN query_records v ON v.snapshot_id=:snapshot AND v.id=wanted.value
            CROSS JOIN records r ON r.snapshot_id=:snapshot AND r.id=v.id
            WHERE v.collection='passages' AND (v.scope_mask & :mask)=v.scope_mask
              AND v.source_id IN (SELECT s.id FROM source_policies s
                    WHERE json_extract(s.rights, '$.' || :purpose)='allowed'
                    AND NOT EXISTS (SELECT 1 FROM withdrawals w WHERE w.id=s.id))
              AND NOT EXISTS (SELECT 1 FROM withdrawals w WHERE w.id=v.id)
              AND EXISTS (SELECT 1 FROM query_records e
                    WHERE e.snapshot_id=:snapshot AND e.collection='entries' AND e.id=v.entry_id
                      AND (e.scope_mask & :mask)=e.scope_mask
                      AND e.source_id IN (SELECT s.id FROM source_policies s
                        WHERE json_extract(s.rights, '$.' || :purpose)='allowed'
                          AND NOT EXISTS (SELECT 1 FROM withdrawals w WHERE w.id=s.id)))
              AND (v.speaker_id IS NULL OR EXISTS (SELECT 1 FROM query_records p
                    WHERE p.snapshot_id=:snapshot AND p.collection='characters' AND p.id=v.speaker_id
                      AND (p.scope_mask & :mask)=p.scope_mask
                      AND p.source_id IN (SELECT s.id FROM source_policies s
                        WHERE json_extract(s.rights, '$.' || :purpose)='allowed'
                          AND NOT EXISTS (SELECT 1 FROM withdrawals w WHERE w.id=s.id))))
            ORDER BY v.position'''
        rows = self.connection.execute(sql, {**self.params, 'selected_ids': json.dumps(list(identifiers))}).fetchall()
        links = self.visible_links()
        result = [json.loads(row[0]) for row in rows]
        for passage in result:
            passage['next_ids'] = [identifier for identifier in passage['next_ids'] if identifier in links.get(passage['id'], ())]
        by_id = {passage['id']: passage for passage in result}
        return [by_id[identifier] for identifier in identifiers if identifier in by_id]

    def sources(self, result):
        identifiers = {record['source_id'] for key in ('entries', 'characters', 'passages', 'relationships', 'results') for record in result.get(key, [])}
        return [dict(json.loads(row['payload']), rights=json.loads(row['rights'])) for row in self.connection.execute(
            "SELECT r.payload,s.rights FROM records r JOIN source_policies s ON s.id=r.id WHERE r.snapshot_id=? AND r.collection='sources' AND r.id IN (SELECT value FROM json_each(?)) ORDER BY r.position", (self.snapshot, json.dumps(sorted(identifiers))))]

    def candidate_plan(self, terms):
        """Internal planning only; candidates never bypass the visible projection."""
        grams = set().union(*(trigrams(term) for term in terms))
        if not grams:
            return {'kind': 'scan', 'candidates': None}
        rows = self.connection.execute('''SELECT gram,passage_count,indexed FROM query_grams
            WHERE snapshot_id=:snapshot AND gram IN (SELECT value FROM json_each(:grams))''',
            {'snapshot': self.snapshot, 'grams': json.dumps(sorted(grams))}).fetchall()
        if len(rows) != len(grams):
            return {'kind': 'empty', 'candidates': 0}
        indexed = [row for row in rows if row['indexed']]
        if not indexed:
            return {'kind': 'scan', 'candidates': None}
        rarest = min(indexed, key=lambda row: (row['passage_count'], row['gram']))
        return {'kind': 'index', 'gram': rarest['gram'], 'candidates': rarest['passage_count']}

    def search_facets(self):
        key = ('search-facets', self.topology_cache_key)
        # Only compact, query-independent metadata is cached at this boundary.
        with _TOPOLOGY_CACHE_LOCK:
            facets = _total_get(key)
            if facets is None:
                # This projection needs only visibility fields. The passage CTE
                # materializes parent IDs, allowing all three record collections
                # to use query_visibility without reading normalized body text.
                facets = [dict(row) for row in self.visibility_rows('''SELECT coalesce(speaker_id,"narration") AS speaker,
                    count(*) AS n FROM passages GROUP BY speaker ORDER BY speaker''')]
                _total_put(key, facets)
            return facets

    def order_search_positions(self, positions):
        """Keep hits compact while using the topology of ALL visible passages."""
        if positions and self.has_backlinks:
            if len(self.visible_links()) > 5000:
                self.ordered_ids()
                positions.sort(key=self._ordered_position_index.__getitem__)
                return
            self.linked_order()
            adjustments = self._position_adjustments
            positions.sort()
            # Ordinary positions already have the right relative order. When no
            # linked node matched, avoid constructing a sort tuple for every hit.
            for position in adjustments:
                index = bisect_left(positions, position)
                if index < len(positions) and positions[index] == position:
                    positions.sort(key=lambda p: adjustments.get(p, (p, -1)))
                    break
        else:
            positions.sort()

    def search_page_ids(self, positions):
        if not positions:
            return []
        rows = self.passage_rows('''SELECT v.id,v.position FROM json_each(:positions) wanted
            CROSS JOIN passages v ON v.position=wanted.value''', {'positions': json.dumps(list(positions))})
        identifiers = {row['position']: row['id'] for row in rows}
        return [identifiers[position] for position in positions]

    def search(self, options, secret):
        query = {key: value for key, value in options.items() if key != 'cursor'}
        binding = fingerprint({'kind': 'indexed_search', 'query': query, **self.meta})
        offset = decode_cursor(options['cursor'], binding, self.revision, secret) if options['cursor'] else 0
        terms = query['q'].split() if query['mode'] == 'keywords' else [query['q']]
        where = ['(:speaker="all" OR coalesce(v.speaker_id,"narration")=:speaker)']
        params = {'speaker': query['speaker']}
        for number, term in enumerate(terms):
            where.append(text_condition(f'term{number}')); params[f'term{number}'] = term
        # The current contract only accepts the quest category, so all/quest have identical matches.
        condition = ' AND '.join(where)
        cache_key = (self.topology_cache_key, tuple(sorted(query.items())))
        cached = _search_get(cache_key)
        if cached is None:
            plan = self.candidate_plan(terms)
            # Facets count ALL visible passages, independently of the query. Share
            # that compact result across misses under the same visibility revision.
            speakers = self.search_facets()
            # Transfer only integer positions. String IDs are resolved for the
            # requested page, after sorting/counting the entire exact result.
            if plan['kind'] == 'scan':
                rows = self.search_rows(f'''SELECT json_group_array(v.position) AS matches
                    FROM passages v WHERE {condition}''', params)
                matches = json.loads(rows[0]['matches'])
            else:
                # A gram match is only a superset. Recheck every term, speaker,
                # permission and withdrawal in the same fixed read transaction.
                matches = [row['position'] for row in self.search_rows(f'''
                    SELECT v.position FROM query_postings candidate CROSS JOIN passages v
                      ON v.position=candidate.position
                    WHERE candidate.snapshot_id=:snapshot AND candidate.gram=:candidate_gram
                      AND {condition}''', {**params, 'candidate_gram': plan['gram']})] if plan['kind'] == 'index' else []
            self.order_search_positions(matches)
            total = len(matches)
            # Signed 64-bit positions match SQLite's integer range. This bounded
            # LRU stores packed numbers rather than a Python object per hit.
            cached = _search_put(cache_key, (array('q', matches), speakers, total))
        matching_positions, speakers, total = cached
        require(offset % query['limit'] == 0 and (offset == 0 or offset < total), 'cursor outside results')
        page_ids = self.search_page_ids(matching_positions[offset:offset + query['limit']])
        payloads = {passage['id']: passage for passage in self.selected('passages', set(page_ids))}
        results = [payloads[identifier] for identifier in page_ids]
        count = sum(row['n'] for row in speakers)
        characters = self.selected('characters', {row['speaker'] for row in speakers if row['speaker'] != 'narration'})
        counts = self.counts(passage_count=count)
        cursor = lambda position: encode_cursor(position, binding, self.revision, secret)
        return {**self.meta, 'storage': 'sqlite', 'query': query, 'results': results,
                'entries': self.selected('entries', {p['entry_id'] for p in results}), 'characters': characters,
                'stats': {key: counts[key] for key in ('passages', 'characters', 'relationships')},
                'facets': {'categories': [{'value': 'quest', 'count': count}] if count else [],
                           'speakers': [{'value': row['speaker'], 'count': row['n']} for row in speakers]},
                'pagination': {'total': total, 'offset': offset, 'limit': query['limit'], 'page': offset // query['limit'] + 1,
                               'pages': max(1, (total + query['limit'] - 1) // query['limit']),
                               'next_cursor': cursor(offset + query['limit']) if offset + query['limit'] < total else None,
                               'previous_cursor': cursor(max(0, offset - query['limit'])) if offset else None}}

    def counts(self, passage_count=None):
        result = {key: self.rows(f'SELECT count(*) FROM {table}')[0][0] for key, table in [('entries', 'entries'), ('characters', 'people'), ('relationships', 'relations')]}
        result['passages'] = passage_count if passage_count is not None else self.rows('SELECT count(*) FROM passages')[0][0]
        return result

    def context(self, passages):
        ids = {p['id'] for p in passages}
        return {**self.meta, 'passages': [{**p, 'next_ids': [i for i in p['next_ids'] if i in ids]} for p in passages],
                'entries': self.selected('entries', {p['entry_id'] for p in passages}),
                'characters': self.selected('characters', {p['speaker_id'] for p in passages if p['speaker_id'] is not None})}

    def passage(self, target, radius):
        if not self.selected('passages', {target}):
            raise GraphUnavailable('该段落在当前范围、用途或快照中不可用。')
        reached = {target}
        for _ in range(radius):
            links = self.rows('''SELECT p.id FROM (
                SELECT to_id AS id FROM query_links WHERE snapshot_id=:snapshot AND from_id IN (SELECT value FROM json_each(:ids))
                UNION SELECT from_id AS id FROM query_links WHERE snapshot_id=:snapshot AND to_id IN (SELECT value FROM json_each(:ids))) l
                CROSS JOIN passages p ON p.id=l.id''', {'ids': json.dumps(sorted(reached))})
            reached.update(row[0] for row in links)
        if len(reached) <= 20:
            candidates = reached
        elif self.has_backlinks:
            candidates = ([target] + [i for i in self.ordered_ids() if i in reached and i != target])[:20]
        else:
            candidates = [row[0] for row in self.rows('SELECT p.id FROM json_each(:ids) wanted CROSS JOIN passages p ON wanted.value=p.id ORDER BY p.id=:target DESC, p.sort_rank LIMIT 20', {'ids': json.dumps(sorted(reached)), 'target': target})]
        result = self.context(self.selected('passages', set(candidates)))
        result.update(target_id=target, radius=radius, truncated=len(reached) > 20,
                      completeness='仅返回当前允许范围的显式相邻连接；缺失处不补写，不保证完整剧情。')
        return result

    def story(self, entry, limit, cursor, secret):
        if not self.selected('entries', {entry}):
            raise GraphUnavailable('该条目在当前范围、用途或快照中不可用。')
        binding = fingerprint({'kind': 'indexed_story', 'entry': entry, 'limit': limit, **self.meta})
        offset = decode_cursor(cursor, binding, self.revision, secret) if cursor else 0
        count = self.rows('SELECT count(*) FROM passages WHERE entry_id=:entry', {'entry': entry})[0][0]
        require(offset % limit == 0 and (offset == 0 or offset < count), 'invalid offset')
        result = self.context(self.records('passages', 'v.entry_id=:entry', {'entry': entry}, 'v.sort_rank', (limit, offset)))
        result.update(entry_id=entry, completeness='只提供显式对白连接与分支；没有推断的章节或时间线。范围内为空不代表原作不存在。',
                      pagination={'offset': offset, 'limit': limit, 'total': count, 'next_cursor': encode_cursor(offset + limit, binding, self.revision, secret) if offset + limit < count else None})
        return result

    def reader(self, target, cursor, secret, limit=50):
        binding = fingerprint({'kind': 'indexed_reader', 'target': target, 'limit': limit, **self.meta})
        total_key = ('reader-total', self.topology_cache_key)
        total = _total_get(total_key)
        if total is None:
            total = _total_put(total_key, self.rows('SELECT count(*) FROM passages')[0][0])
        offset = 0
        if cursor:
            offset = decode_cursor(cursor, binding, self.revision, secret)
        elif target:
            rows = self.rows('SELECT sort_rank FROM passages WHERE id=:id', {'id': target})
            if not rows:
                raise GraphUnavailable('这个位置在当前范围、用途或快照中不可用，未自动扩大范围。')
            if self.has_backlinks:
                linked = self.linked_order()
                if len(linked) > 5000:
                    self.ordered_ids()
                    preceding = self._ordered_index[target]
                    self._dense_order = True
                    self._order_adjustments = {}
                else:
                    positions = {row['id']: row['position'] for row in self.visible_passage_rows()}
                    target_position = positions[target]
                    target_key = linked.get(target, (target_position, -1))
                    preceding = sum(1 for identifier, position in positions.items()
                                    if linked.get(identifier, (position, -1)) < target_key)
            else:
                preceding = self.rows('SELECT count(*) FROM passages WHERE sort_rank<:rank', {'rank': rows[0][0]})[0][0]
            offset = preceding // limit * limit
        require(offset % limit == 0 and (offset == 0 or offset < total), 'reader cursor outside results')
        page_key = (self.topology_cache_key, offset, limit)
        with _TOPOLOGY_CACHE_LOCK:
            passages = _PAGE_CACHE.get(page_key)
            if passages is None:
                identifiers = self.ordered_page('1', {}, (limit, offset))
                passages = self.passage_page(identifiers)
                _PAGE_CACHE[page_key] = passages
                _PAGE_CACHE.move_to_end(page_key)
                while len(_PAGE_CACHE) > _PAGE_CACHE_LIMIT:
                    _PAGE_CACHE.popitem(last=False)
        result = self.context(passages)
        result['passages'] = passages  # Visible off-page next links remain navigable.
        result['target_id'] = target if target in {p['id'] for p in passages} else None
        result['pagination'] = {'offset': offset, 'limit': limit, 'total': total,
                                'next_cursor': encode_cursor(offset + limit, binding, self.revision, secret) if offset + limit < total else None,
                                'previous_cursor': encode_cursor(max(0, offset - limit), binding, self.revision, secret) if offset else None}
        return result

    def graph_bundle(self, relationships, characters):
        evidence = {i for r in relationships for group in r['evidence_groups'] for i in group}
        passages = self.selected('passages', evidence)
        return {**self.meta, 'relationships': relationships, 'characters': characters, 'passages': passages,
                'entries': self.selected('entries', {p['entry_id'] for p in passages})}

    def graph(self, options, secret):
        nodes = {options['center']}
        if not self.selected('characters', nodes):
            raise GraphUnavailable('当前人物在此范围、用途或快照中不可用。')
        from graph_archive import conditioned
        relations = {}
        for _ in range(options['hops']):
            candidates = self.records('relationships', '(v.from_id IN (SELECT value FROM json_each(:ids)) OR v.to_id IN (SELECT value FROM json_each(:ids)))', {'ids': json.dumps(sorted(nodes))})
            for relation in candidates:
                if (options['predicate'] == 'all' or options['predicate'] == relation['predicate']) and conditioned(relation, options['condition']):
                    relations[relation['id']] = relation
            nodes.update(i for r in relations.values() for i in (r['from_id'], r['to_id']))
        # Include edges between discovered nodes, just like the established graph semantics.
        candidates = self.records('relationships', 'v.from_id IN (SELECT value FROM json_each(:ids)) AND v.to_id IN (SELECT value FROM json_each(:ids))', {'ids': json.dumps(sorted(nodes))})
        selected = [r for r in candidates if (options['predicate'] == 'all' or options['predicate'] == r['predicate']) and conditioned(r, options['condition'])]
        # Determine the page using only identities/relationships. Fetch its evidence
        # afterwards so a large neighborhood never hydrates every evidence text.
        view = {**self.meta, 'relationships': selected, 'characters': self.selected('characters', nodes), 'passages': [], 'entries': []}
        result = graph_view(view, options, secret, revision=self.revision)
        bundle = self.graph_bundle(result['relationships'], result['characters'])
        evidence = {p['id'] for p in bundle['passages']}
        result['passages'] = [{**p, 'next_ids': [i for i in p['next_ids'] if i in evidence]} for p in bundle['passages']]
        result['entries'] = bundle['entries']
        revision_content = {key: value for key, value in result.items() if key not in ('purpose', 'pagination', 'content_revision')}
        revision_content['pagination'] = {key: value for key, value in result['pagination'].items() if not key.endswith('cursor')}
        result['content_revision'] = fingerprint(revision_content)
        return result

    def relationship(self, identifier):
        relationships = self.selected('relationships', {identifier})
        if not relationships:
            raise GraphUnavailable('该关系或完整证据在当前范围、用途或快照中不可用。')
        return relation_view(self.graph_bundle(relationships, self.selected('characters', {i for r in relationships for i in (r['from_id'], r['to_id'])})), identifier)

    def characters(self, query):
        require(len(query) <= 160, 'character query too long')
        characters = self.records('characters', 'instr(v.name,:q)>0 OR instr(v.id,:q)>0', {'q': query}, limit=(21, 0))
        return {**self.meta, 'characters': characters[:20], 'truncated': len(characters) > 20}
