import json
import random
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from archive_store import StoreError, connect, import_snapshot, load_snapshot
from benchmark_boundaries import workload
from graph_archive import graph_view, relation_view
from indexed_archive import indexed_view
from query_index import prepare_indexes
from search_archive import search_options, search_view, ordered_passages, StaleCursor
from test_graph_archive import SAMPLE, SECRET, next_snapshot, options
from validate_sample import project, SampleError


class IndexedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / 'archive.sqlite3'
        import_snapshot(SAMPLE, self.database)

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_database_reports_unavailable(self):
        with self.assertRaises(StoreError), indexed_view(Path(self.temp.name) / 'missing.sqlite3', None, ['opening'], 'display'):
            pass

    def test_candidate_filter_is_a_superset_with_literal_and_unicode_parity(self):
        data, _ = workload('long', 300)
        texts = ['abcdef', 'abc bcd cde def', 'ＡＢＣ "_%" e\u0301 🙂🚀界 空\x00白',
                 'abc', '甲乙丙 丁戊己', '甲乙丙 其他', '丁戊己 其他']
        for passage, text in zip(data['passages'][32:], texts):
            passage['text'] = text
        import_snapshot(data, self.database, activate=True)
        view = project(data, ['opening'])
        with indexed_view(self.database, None, ['opening'], 'display') as archive:
            self.assertEqual(archive.candidate_plan(['abcdef'])['kind'], 'index')
            self.assertEqual(archive.candidate_plan(['abcdef'])['candidates'], 2)
            self.assertEqual(archive.candidate_plan(['物资核对'])['kind'], 'scan')
            self.assertEqual(archive.candidate_plan(['无此词'])['kind'], 'empty')
            for query in ('abcdef', 'ＡＢＣ', 'abc', '"_%"', 'e\u0301', '🙂🚀界', '空\x00白',
                          '物资核对', '文', '🙂🚀', '', '甲乙丙 丁戊己', '甲乙丙 其', '无此词'):
                for mode in ('literal', 'keywords'):
                    with self.subTest(query=query, mode=mode):
                        opts = search_options({'q': [query], 'mode': [mode], 'limit': ['50']})
                        result = archive.search(opts, SECRET)
                        expected = search_view(view, opts, SECRET)
                        for key in ('results', 'facets', 'stats'):
                            self.assertEqual(result[key], expected[key])
                        self.assertEqual(result['pagination']['total'], expected['pagination']['total'])

    def test_candidate_posting_budget_falls_back_without_losing_results(self):
        data, _ = workload('long', 300)
        with patch('query_index.MAX_POSTINGS_PER_PASSAGE', 0):
            import_snapshot(data, self.database, activate=True)
        with indexed_view(self.database, None, ['opening'], 'display') as archive:
            self.assertEqual(archive.candidate_plan(['组号07'])['kind'], 'scan')
            opts = search_options({'q': ['组号07']})
            self.assertEqual(archive.search(opts, SECRET)['results'],
                             search_view(project(data, ['opening']), opts, SECRET)['results'])

    def test_scan_reuses_facets_without_narrowing_them_to_matches(self):
        data, _ = workload('long', 300)
        for index, passage in enumerate(data['passages'][32:]):
            passage['text'] = '共用正文 ＡＢＣ "_%" 空\x00白 🙂🚀界'
            passage['speaker_id'] = 'person:student' if index % 2 else 'person:merchant'
        import_snapshot(data, self.database, activate=True)
        snapshot = data['snapshot_id']

        def check_queries():
            for scopes in (['opening'], data['scope_ids']):
                for purpose in ('display', 'export', 'external_ai'):
                    view = project(load_snapshot(self.database, snapshot), scopes, purpose)
                    # Different terms/speakers miss the result cache but reuse the
                    # same facets. Hidden/zero hits must still count all visible text.
                    for query, mode, speaker in (
                        ('不存在的词', 'literal', 'all'),
                        ('共用正文', 'literal', 'person:student'),
                        ('ＡＢＣ 空\x00白', 'keywords', 'person:merchant'),
                        ('🙂🚀', 'literal', 'all'),
                        ('', 'literal', 'narration'),
                    ):
                        opts = search_options({'q': [query], 'mode': [mode], 'speaker': [speaker], 'limit': ['50']})
                        expected = search_view(view, opts, SECRET)
                        with indexed_view(self.database, snapshot, scopes, purpose) as archive:
                            actual = archive.search(opts, SECRET)
                        for key in ('results', 'facets', 'stats', 'characters'):
                            self.assertEqual(actual[key], expected[key])
                        self.assertEqual(actual['pagination']['total'], expected['pagination']['total'])

        check_queries()
        updated = next_snapshot(data, 'scan-facets-restricted')
        updated['withdrawn_ids'] = ['person:merchant', data['passages'][33]['id']]
        updated['sources'][1]['rights']['display'] = 'denied'
        import_snapshot(updated, self.database, activate=True)
        # The old snapshot must also use the new withdrawal/purpose boundary.
        check_queries()

    def test_candidate_indexes_migrate_all_snapshots_atomically(self):
        updated = next_snapshot(SAMPLE, 'candidate-migration-new')
        updated['withdrawn_ids'] = ['passage:03']
        updated['sources'][1]['rights']['display'] = 'denied'
        import_snapshot(updated, self.database, activate=True)
        with closing(connect(self.database, writable=True)) as connection:
            connection.execute('DROP TABLE query_postings')
            connection.execute('DROP TABLE query_grams')
            connection.execute('UPDATE query_state SET version=1')
        with self.assertRaises(StoreError), indexed_view(self.database, None, ['opening'], 'display'):
            pass
        with patch('query_index.build_candidates', side_effect=RuntimeError('interrupted rebuild')):
            with self.assertRaises(RuntimeError):
                prepare_indexes(self.database)
        with closing(connect(self.database)) as connection:
            self.assertEqual(connection.execute('SELECT version FROM query_state').fetchone()[0], 1)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='query_grams'").fetchone())
        result = prepare_indexes(self.database)
        self.assertEqual(result['index_version'], 2)
        self.assertEqual(set(result['rebuilt_snapshots']), {SAMPLE['snapshot_id'], updated['snapshot_id']})
        for snapshot in result['rebuilt_snapshots']:
            opts = search_options({'q': ['物资']})
            expected = search_view(project(load_snapshot(self.database, snapshot), ['opening']), opts, SECRET)
            with indexed_view(self.database, snapshot, ['opening'], 'display') as archive:
                actual = archive.search(opts, SECRET)
            for key in ('results', 'facets', 'stats'):
                self.assertEqual(actual[key], expected[key])

    def test_search_parity_across_scopes_purposes_and_filters(self):
        for scopes in (['opening'], SAMPLE['scope_ids'], ['opening', 'east'], ['opening', 'west'], ['later']):
            for purpose in ('display', 'export', 'external_ai'):
                view = project(SAMPLE, scopes, purpose)
                with indexed_view(self.database, None, scopes, purpose) as archive:
                    for query in ({}, {'q': ['先核对物资']}, {'q': ['阿 青'], 'mode': ['keywords']}, {'speaker': ['narration']}):
                        with self.subTest(scopes=scopes, purpose=purpose, query=query):
                            opts = search_options(query)
                            expected = search_view(view, opts, SECRET)
                            actual = archive.search(opts, SECRET)
                            for key in ('results', 'entries', 'characters', 'stats', 'facets', 'query'):
                                self.assertEqual(actual[key], expected[key], key)
                            for key in ('offset', 'limit', 'total', 'page', 'pages'):
                                self.assertEqual(actual['pagination'][key], expected['pagination'][key])

    def test_graph_and_evidence_parity(self):
        for scopes in (['opening'], SAMPLE['scope_ids'], ['opening', 'east'], ['opening', 'west']):
            for purpose in ('display', 'export', 'external_ai'):
                view = project(SAMPLE, scopes, purpose)
                with indexed_view(self.database, None, scopes, purpose) as archive:
                    actual = archive.graph(options(), SECRET)
                    expected = graph_view(view, options(), SECRET)
                    for key in ('characters', 'relationships', 'passages', 'entries'):
                        self.assertEqual(actual[key], expected[key])
                    self.assertEqual(archive.relationship('relation:mentor'), relation_view(view, 'relation:mentor'))

    def test_grouped_search_restores_source_order_without_backlinks(self):
        data = next_snapshot(SAMPLE, 'unlinked-search')
        for passage in data['passages']:
            passage['next_ids'] = []
        import_snapshot(data, self.database, activate=True)
        view = project(data, data['scope_ids'])
        self.assertGreater(len({p['speaker_id'] for p in view['passages']}), 1)
        with indexed_view(self.database, None, data['scope_ids'], 'display') as archive:
            self.assertFalse(archive.has_backlinks)
            opts = search_options({'limit': ['50']})
            expected = search_view(view, opts, SECRET)
            actual = archive.search(opts, SECRET)
            for key in ('results', 'facets', 'stats'):
                self.assertEqual(actual[key], expected[key])

    def test_reader_target_pages_and_cursor_bindings(self):
        with indexed_view(self.database, None, ['opening'], 'display') as archive:
            expected = ordered_passages(project(SAMPLE, ['opening'])['passages'])
            first = archive.reader('passage:03', None, SECRET, limit=2)
            self.assertIn('passage:03', [p['id'] for p in first['passages']])
            token = first['pagination']['next_cursor']
            second = archive.reader('passage:03', token, SECRET, limit=2)
            self.assertEqual(second['passages'], expected[second['pagination']['offset']:second['pagination']['offset'] + 2])
            back = archive.reader('passage:03', second['pagination']['previous_cursor'], SECRET, limit=2)
            self.assertEqual(back, first)
            for target, limit, secret in ((None, 2, SECRET), ('passage:03', 3, SECRET), ('passage:03', 2, b'other')):
                with self.assertRaises(SampleError):
                    archive.reader(target, token, secret, limit=limit)
        for scopes, purpose in ((['opening', 'later'], 'display'), (['opening'], 'export')):
            with indexed_view(self.database, None, scopes, purpose) as archive, self.assertRaises(SampleError):
                archive.reader('passage:03', token, SECRET, limit=2)
        data = next_snapshot(SAMPLE, 'another-snapshot')
        import_snapshot(data, self.database, activate=True)
        with indexed_view(self.database, None, ['opening'], 'display') as archive, self.assertRaises(SampleError):
            archive.reader('passage:03', token, SECRET, limit=2)

    def test_policy_tightening_invalidates_cursor_without_rebuild(self):
        with indexed_view(self.database, None, SAMPLE['scope_ids'], 'display') as archive:
            cursor = archive.reader(None, None, SECRET, limit=2)['pagination']['next_cursor']
        with closing(connect(self.database, writable=True)) as connection:
            source = SAMPLE['sources'][1]
            rights = dict(source['rights'], display='denied')
            connection.execute('UPDATE source_policies SET rights=? WHERE id=?', (json.dumps(rights), source['id']))
        with indexed_view(self.database, None, SAMPLE['scope_ids'], 'display') as archive:
            with self.assertRaises(StaleCursor):
                archive.reader(None, cursor, SECRET, limit=2)
            expected = project(load_snapshot(self.database), SAMPLE['scope_ids'])
            self.assertEqual(archive.counts()['passages'], len(expected['passages']))

    def assert_reader_matches_projection(self, snapshot, scopes, purpose, limit=7):
        expected = ordered_passages(project(load_snapshot(self.database, snapshot), scopes, purpose)['passages'])
        cursor = None
        actual = []
        while True:
            # Each page is a new transaction, as it is for separate HTTP requests.
            with indexed_view(self.database, snapshot, scopes, purpose) as archive:
                page = archive.reader(None, cursor, SECRET, limit=limit)
            self.assertEqual(page['pagination']['total'], len(expected))
            self.assertEqual(page['pagination']['offset'], len(actual))
            actual.extend(page['passages'])
            cursor = page['pagination']['next_cursor']
            if not cursor:
                break
        self.assertEqual(actual, expected)
        if expected:
            target = expected[-1]['id']
            with indexed_view(self.database, snapshot, scopes, purpose) as archive:
                page = archive.reader(target, None, SECRET, limit=limit)
            self.assertEqual(page['target_id'], target)
            self.assertEqual(page['passages'], expected[(len(expected) - 1) // limit * limit:])

    def test_reader_cache_isolated_by_snapshot_scope_and_purpose(self):
        updated = next_snapshot(SAMPLE, 'reader-cache-new')
        updated['passages'][0]['text'] = '新快照的正文，旧快照仍保留原句。'
        import_snapshot(updated, self.database, activate=True)
        boundaries = [(snapshot, scopes, purpose)
            for snapshot in (SAMPLE['snapshot_id'], updated['snapshot_id'])
            for scopes in (['opening'], ['opening', 'west'], SAMPLE['scope_ids'])
            for purpose in ('display', 'export', 'external_ai')]
        for boundary in boundaries:
            with self.subTest(boundary=boundary):
                self.assert_reader_matches_projection(*boundary)
                self.assert_reader_matches_projection(*boundary)

    def test_reader_cached_pages_and_totals_follow_new_restrictions(self):
        for change in ('policy', 'withdrawal'):
            with self.subTest(change=change):
                self.database = Path(self.temp.name) / f'{change}.sqlite3'
                import_snapshot(SAMPLE, self.database)
                snapshot = SAMPLE['snapshot_id']
                scopes = SAMPLE['scope_ids']
                for purpose in ('display', 'export', 'external_ai'):
                    self.assert_reader_matches_projection(snapshot, scopes, purpose)
                with indexed_view(self.database, snapshot, scopes, 'display') as archive:
                    token = archive.reader(None, None, SECRET, limit=7)['pagination']['next_cursor']
                updated = next_snapshot(SAMPLE, f'reader-cache-{change}')
                if change == 'policy':
                    updated['sources'][1]['rights']['display'] = 'denied'
                else:
                    updated['withdrawn_ids'].extend(['passage:03', 'person:merchant'])
                import_snapshot(updated, self.database, activate=True)
                with indexed_view(self.database, snapshot, scopes, 'display') as archive:
                    with self.assertRaises(StaleCursor):
                        archive.reader(None, token, SECRET, limit=7)
                for purpose in ('display', 'export', 'external_ai'):
                    self.assert_reader_matches_projection(snapshot, scopes, purpose)
                    self.assert_reader_matches_projection(updated['snapshot_id'], scopes, purpose)

    def test_small_neighborhood_does_not_read_archive_topology(self):
        with indexed_view(self.database, None, ['opening'], 'external_ai') as archive:
            with patch.object(archive, 'ordered_ids', side_effect=AssertionError('Unneeded archive scan')):
                result = archive.passage('passage:03', 1)
            self.assertEqual({p['id'] for p in result['passages']}, {'passage:02', 'passage:03', 'passage:04'})
            self.assertFalse(result['truncated'])

    def test_corrupted_indexes_fail_closed_and_explicit_rebuild_repairs(self):
        mutations = [
            "UPDATE query_records SET text_norm='tampered' WHERE id='passage:03'",
            "DELETE FROM query_links WHERE from_id='passage:03'",
            "DELETE FROM query_evidence WHERE relation_id='relation:mentor'",
            "DELETE FROM query_postings WHERE snapshot_id='fixture-2026-10-10-v1'",
            'UPDATE query_grams SET passage_count=0',
            'UPDATE query_snapshots SET ready=0',
        ]
        for sql in mutations:
            with self.subTest(sql=sql):
                with closing(connect(self.database, writable=True)) as connection:
                    connection.execute(sql)
                with self.assertRaises(StoreError), indexed_view(self.database, None, ['opening'], 'display'):
                    pass
                self.assertEqual(prepare_indexes(self.database)['rebuilt_snapshots'], [SAMPLE['snapshot_id']])
                with indexed_view(self.database, None, ['opening'], 'display') as archive:
                    self.assertEqual(archive.passage('passage:03', 0)['target_id'], 'passage:03')

    def test_corrupt_source_records_cannot_be_rebuilt(self):
        with closing(connect(self.database, writable=True)) as connection:
            connection.execute("UPDATE records SET payload=json_set(payload,'$.text','tampered') WHERE id='passage:03'")
        with self.assertRaises(StoreError), indexed_view(self.database, None, ['opening'], 'display'):
            pass
        with self.assertRaises(StoreError):
            prepare_indexes(self.database)

    def test_startup_migrates_legacy_database_and_reads_do_not_write(self):
        with closing(connect(self.database, writable=True)) as connection:
            triggers = connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
            for row in triggers:
                connection.execute(f'DROP TRIGGER "{row[0]}"')
            for table in ('query_records', 'query_links', 'query_evidence', 'query_grams', 'query_postings', 'query_snapshots', 'query_state'):
                connection.execute(f'DROP TABLE {table}')
        with self.assertRaises(StoreError), indexed_view(self.database, None, ['opening'], 'display'):
            pass
        self.assertEqual(prepare_indexes(self.database)['rebuilt_snapshots'], [SAMPLE['snapshot_id']])
        before = self.database.read_bytes()
        with indexed_view(self.database, None, ['opening'], 'display') as archive:
            archive.search(search_options({}), SECRET)
            archive.reader(None, None, SECRET)
            archive.graph(options(), SECRET)
        self.assertEqual(self.database.read_bytes(), before)

    def test_sparse_order_matches_full_topology_through_all_pages(self):
        # Shuffled DAGs mix backward links, joins, isolated nodes and invisible
        # predecessors. Match filtering must happen after visible topology.
        for seed in range(6):
            rng = random.Random(seed)
            data = next_snapshot(SAMPLE, f'order-{seed}')
            template = data['passages'][0]
            data['relationships'] = [{**data['relationships'][0], 'evidence_groups': [['passage:random-001']]}]
            data['passages'] = [{**template, 'id': f'passage:random-{index:03}',
                'text': '命中' if index % 3 else '其他',
                'required_scope_ids': ['opening', 'later'] if index % 5 == 0 else ['opening'],
                'source_locator': f'data/samples/story.json#/passages/{index}', 'next_ids': []}
                for index in range(60)]
            order = list(range(60)); rng.shuffle(order)
            for position, index in enumerate(order):
                if position % 3:
                    data['passages'][index]['next_ids'] = [data['passages'][following]['id']
                        for following in rng.sample(order[position + 1:], min(2, len(order) - position - 1))]
            data['withdrawn_ids'] = [data['passages'][seed]['id']]
            import_snapshot(data, self.database, activate=True)
            stored = load_snapshot(self.database)
            for scopes in (['opening'], ['opening', 'later']):
                for query in ('', '命中'):
                    with self.subTest(seed=seed, scopes=scopes, query=query):
                        view = project(stored, scopes)
                        expected = [p for p in ordered_passages(view['passages']) if query in p['text']]
                        with indexed_view(self.database, None, scopes, 'display') as archive:
                            cursor = ''; actual = []
                            while True:
                                page = archive.search(search_options({'q': [query], 'limit': ['7'],
                                    'snapshot': [data['snapshot_id']], **({'cursor': [cursor]} if cursor else {})}), SECRET)
                                actual.extend(page['results'])
                                self.assertEqual(page['pagination']['total'], len(expected))
                                cursor = page['pagination']['next_cursor']
                                if not cursor:
                                    break
                            self.assertEqual(actual, expected)
                # Reader pages and target positioning use a separate sparse path.
                self.assert_reader_matches_projection(data['snapshot_id'], scopes, 'display')

    def test_search_normalization_literal_characters_and_keyword_and(self):
        data = next_snapshot(SAMPLE, 'normalization')
        data['passages'][0]['text'] = 'ＡＢＣ\t  中文词句\n"%_" 🙂🙂🙂 abC'
        import_snapshot(data, self.database, activate=True)
        view = project(data, ['opening'])
        with indexed_view(self.database, None, ['opening'], 'display') as archive:
            for query in ('ＡＢＣ', 'ABC', 'abc', '中文', '文', '"%_"', '🙂🙂🙂', 'ＡＢＣ\n中文词句', '中文词句 ABC'):
                for mode in ('literal', 'keywords'):
                    for speaker in ('all', 'narration', 'person:student'):
                        with self.subTest(query=query, mode=mode, speaker=speaker):
                            opts = search_options({'q': [query], 'mode': [mode], 'speaker': [speaker]})
                            actual = archive.search(opts, SECRET)
                            expected = search_view(view, opts, SECRET)
                            self.assertEqual(actual['results'], expected['results'])
                            self.assertEqual(actual['pagination']['total'], expected['pagination']['total'])
                            self.assertEqual(actual['facets'], expected['facets'])

    def test_search_stale_cursor_and_facets_after_new_restrictions(self):
        opts = search_options({'limit': ['2']})
        with indexed_view(self.database, None, ['opening'], 'display') as archive:
            first = archive.search(opts, SECRET)
        update = next_snapshot(SAMPLE, 'restricted-search')
        update['withdrawn_ids'] = ['passage:03', 'person:merchant']
        import_snapshot(update, self.database, activate=True)
        view = project(load_snapshot(self.database, SAMPLE['snapshot_id']), ['opening'])
        with indexed_view(self.database, SAMPLE['snapshot_id'], ['opening'], 'display') as archive:
            with self.assertRaises(StaleCursor):
                archive.search({**opts, 'cursor': first['pagination']['next_cursor']}, SECRET)
            result = archive.search(opts, SECRET)
            expected = search_view(view, opts, SECRET)
            for key in ('results', 'facets', 'stats'):
                self.assertEqual(result[key], expected[key])


if __name__ == '__main__':
    unittest.main()
