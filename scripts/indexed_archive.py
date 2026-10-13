"""Bounded reads from validated SQLite indexes; live restrictions in one transaction."""
import json
import sqlite3
from contextlib import contextmanager

from archive_store import StoreError, SnapshotNotFound, connect, ensure_schema
from graph_archive import GraphUnavailable, graph_view, relation_view
from query_index import VERSION
from search_archive import fingerprint, encode_cursor, decode_cursor, ordered_passages
from validate_sample import require


@contextmanager
def indexed_view(database, snapshot, scopes, purpose):
    connection = None
    try:
        connection = connect(database)
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
        self.scopes = sorted(set(scopes)); self.purpose = purpose
        self.mask = sum(1 << self.metadata['scope_ids'].index(scope) for scope in self.scopes)
        self.meta = {key: self.metadata[key] for key in ('dataset_kind', 'notice', 'snapshot_id')}
        self.meta.update(scope_ids=self.scopes, purpose=purpose)
        # Conservative invalidation: any restriction update invalidates continuations,
        # including old snapshots. No raw policy counts or revision are exposed.
        self.revision = fingerprint({'snapshot': row['content_hash'], 'policy': state['policy_revision']})
        self.params = {'snapshot': snapshot, 'mask': self.mask, 'purpose': purpose}
        self.cte = '''WITH base AS NOT MATERIALIZED (
          SELECT q.* FROM query_records q JOIN source_policies s ON q.source_id=s.id
          WHERE q.snapshot_id=:snapshot AND (q.scope_mask & :mask)=q.scope_mask
          AND json_extract(s.rights, '$.' || :purpose)='allowed'
          AND NOT EXISTS(SELECT 1 FROM withdrawals w WHERE w.id=q.id OR w.id=q.source_id)
        ), people AS NOT MATERIALIZED (SELECT * FROM base WHERE collection='characters'),
        entries AS NOT MATERIALIZED (SELECT * FROM base WHERE collection='entries'),
        passages AS NOT MATERIALIZED (
          SELECT p.* FROM base p WHERE p.collection='passages'
          AND EXISTS(SELECT 1 FROM entries e WHERE e.id=p.entry_id)
          AND (p.speaker_id IS NULL OR EXISTS(SELECT 1 FROM people c WHERE c.id=p.speaker_id))
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

    def rows(self, sql, parameters=None):
        return self.connection.execute(self.cte + sql, {**self.params, **(parameters or {})}).fetchall()

    def records(self, collection, where='1', parameters=None, order='v.position', limit=None, identifiers=None):
        table = {'characters': 'people', 'entries': 'entries', 'passages': 'passages', 'relationships': 'relations'}[collection]
        ordering = ''
        if order == 'v.sort_rank' and self.has_backlinks:
            ordering = ' JOIN json_each(:ordered) ord ON ord.value=v.id'
            parameters = {**(parameters or {}), 'ordered': json.dumps(self.ordered_ids())}
            order = 'CAST(ord.key AS INTEGER)'
        origin = f'{table} v'
        if identifiers is not None:
            origin = f'json_each(:selected_ids) wanted CROSS JOIN {table} v ON wanted.value=v.id'
            parameters = {**(parameters or {}), 'selected_ids': json.dumps(sorted(identifiers))}
        sql = f'SELECT r.payload FROM {origin} CROSS JOIN records r ON r.snapshot_id=:snapshot AND r.id=v.id{ordering} WHERE {where} ORDER BY {order}'
        if limit is not None:
            sql += ' LIMIT :take OFFSET :skip'
            parameters = {**(parameters or {}), 'take': limit[0], 'skip': limit[1]}
        result = [json.loads(row[0]) for row in self.rows(sql, parameters)]
        if collection == 'passages':
            for passage in result:
                visible = {row[0] for row in self.rows('SELECT p.id FROM query_links l CROSS JOIN passages p ON l.to_id=p.id WHERE l.snapshot_id=:snapshot AND l.from_id=:id', {'id': passage['id']})}
                passage['next_ids'] = [identifier for identifier in passage['next_ids'] if identifier in visible]
        elif collection == 'relationships':
            for relation in result:
                allowed = {row[0] for row in self.rows('SELECT group_number FROM groups WHERE relation_id=:id', {'id': relation['id']})}
                relation['evidence_groups'] = [group for number, group in enumerate(relation['evidence_groups']) if number in allowed]
        return result

    def ordered_ids(self):
        # Rare out-of-order source occurrences need topology of the visible graph,
        # not a filtered global ranking. Fetch only IDs/links, never all text bodies.
        if self._ordered is None:
            nodes = {row[0]: {'id': row[0], 'next_ids': []} for row in self.rows('SELECT id FROM passages ORDER BY position')}
            for row in self.connection.execute('SELECT from_id,to_id FROM query_links WHERE snapshot_id=?', (self.snapshot,)):
                if row[0] in nodes and row[1] in nodes:
                    nodes[row[0]]['next_ids'].append(row[1])
            self._ordered = [p['id'] for p in ordered_passages(list(nodes.values()))]
        return self._ordered

    def selected(self, collection, identifiers):
        if not identifiers:
            return []
        return self.records(collection, identifiers=identifiers)

    def sources(self, result):
        identifiers = {record['source_id'] for key in ('entries', 'characters', 'passages', 'relationships', 'results') for record in result.get(key, [])}
        return [dict(json.loads(row['payload']), rights=json.loads(row['rights'])) for row in self.connection.execute(
            "SELECT r.payload,s.rights FROM records r JOIN source_policies s ON s.id=r.id WHERE r.snapshot_id=? AND r.collection='sources' AND r.id IN (SELECT value FROM json_each(?)) ORDER BY r.position", (self.snapshot, json.dumps(sorted(identifiers))))]

    def search(self, options, secret):
        query = {key: value for key, value in options.items() if key != 'cursor'}
        binding = fingerprint({'kind': 'indexed_search', 'query': query, **self.meta})
        offset = decode_cursor(options['cursor'], binding, self.revision, secret) if options['cursor'] else 0
        terms = query['q'].split() if query['mode'] == 'keywords' else [query['q']]
        where = ['(:speaker="all" OR coalesce(v.speaker_id,"narration")=:speaker)']
        params = {'speaker': query['speaker']}
        for number, term in enumerate(terms):
            where.append(f'instr(v.text_norm,:term{number})>0'); params[f'term{number}'] = term
        # The current contract only accepts the quest category, so all/quest have identical matches.
        condition = ' AND '.join(where)
        total = self.rows(f'SELECT count(*) FROM passages v WHERE {condition}', params)[0][0]
        require(offset % query['limit'] == 0 and (offset == 0 or offset < total), 'cursor outside results')
        results = self.records('passages', condition, params, order='v.sort_rank', limit=(query['limit'], offset)) if total else []
        speakers = self.rows('SELECT coalesce(speaker_id,"narration") AS speaker,count(*) AS n FROM passages GROUP BY speaker ORDER BY speaker')
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
        total = self.rows('SELECT count(*) FROM passages')[0][0]
        offset = 0
        if cursor:
            offset = decode_cursor(cursor, binding, self.revision, secret)
        elif target:
            rows = self.rows('SELECT sort_rank FROM passages WHERE id=:id', {'id': target})
            if not rows:
                raise GraphUnavailable('这个位置在当前范围、用途或快照中不可用，未自动扩大范围。')
            preceding = self.ordered_ids().index(target) if self.has_backlinks else self.rows('SELECT count(*) FROM passages WHERE sort_rank<:rank', {'rank': rows[0][0]})[0][0]
            offset = preceding // limit * limit
        require(offset % limit == 0 and (offset == 0 or offset < total), 'reader cursor outside results')
        passages = self.records('passages', order='v.sort_rank', limit=(limit, offset))
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
