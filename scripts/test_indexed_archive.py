import json
import random
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from archive_store import StoreError, connect, import_snapshot, load_snapshot
from benchmark_boundaries import workload
from graph_archive import graph_view, relation_view
from indexed_archive import indexed_view
from query_index import VERSION, prepare_indexes
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

    def test_text_edges_preserve_middle_boundary_long_and_nul_matches(self):
        data, _ = workload('long', 300)
        texts = ['首端命中 ＡＢＣ 空\x00白 🙂🚀' + '垫' * 200 + '尾端命中',
                 '垫' * 80 + '中段命中' + '垫' * 80,
                 '垫' * 62 + '跨边界匹配' + '垫' * 100,
                 '甲' * 140 + '乙' * 140,
                 'prefixfake' + '隔' * 160 + 'suffixfake']
        for number, passage in enumerate(data['passages'][32:]):
            passage['text'] = texts[number % len(texts)]
        import_snapshot(data, self.database, activate=True)
        for scopes in (['opening'], data['scope_ids']):
            for purpose in ('display', 'export', 'external_ai'):
                view = project(data, scopes, purpose)
                with indexed_view(self.database, None, scopes, purpose) as archive:
                    # Force exact scanning even when grams could reject the query,
                    # exercising the excerpt/fallback boundary itself.
                    with patch.object(archive, 'candidate_plan', return_value={'kind': 'scan', 'candidates': None}):
                        for query in ('首端命中', '尾端命中', '中段命中', '跨边界匹配', '甲' * 70,
                                      '甲' * 60 + '乙' * 60, 'prefixfakesuffixfake', 'ＡＢＣ',
                                      '空\x00白', '🙂🚀', '垫', '', '首端命中 尾端命中'):
                            for mode in ('literal', 'keywords'):
                                opts = search_options({'q': [query], 'mode': [mode]})
                                actual = archive.search(opts, SECRET)
                                expected = search_view(view, opts, SECRET)
                                for key in ('results', 'facets', 'stats'):
                                    self.assertEqual(actual[key], expected[key], (scopes, purpose, query, mode, key))
                                self.assertEqual(actual['pagination']['total'], expected['pagination']['total'])

    def test_text_edges_skip_body_only_when_an_excerpt_proves_the_match(self):
        data, _ = workload('long', 300)
        text = '首端命中' + '垫' * 80 + '中段命中' + '垫' * 80 + '尾端命中'
        for passage in data['passages'][32:]:
            passage['text'] = text
        import_snapshot(data, self.database, activate=True)
        with indexed_view(self.database, None, ['opening'], 'display') as archive:
            body_reads = []

            def observe_body(body, term):
                if body == text:
                    body_reads.append(term)
                return int(term in body)

            archive.connection.create_function('observe_body', 2, observe_body)
            original = archive.search_rows

            def observe(sql, parameters=None):
                return original(sql.replace('ELSE instr(v.text_norm,', 'ELSE observe_body(v.text_norm,'), parameters)

            with patch.object(archive, 'search_rows', side_effect=observe):
                for query, expected_reads in [('首端命中', 0), ('尾端命中', 0), ('中段命中', 268)]:
                    body_reads.clear()
                    opts = search_options({'q': [query]})
                    self.assertEqual(archive.candidate_plan([query])['kind'], 'scan')
                    result = archive.search(opts, SECRET)
                    self.assertEqual(result['pagination']['total'], 268)
                    self.assertEqual(len(body_reads), expected_reads)

    def test_text_index_v3_migration_and_rollback(self):
        with closing(connect(self.database, writable=True)) as connection:
            connection.execute('DROP INDEX query_search_text')
            connection.execute('UPDATE query_state SET version=3')
            before = tuple(connection.execute('SELECT * FROM query_state').fetchone())
            connection.execute('UPDATE query_snapshots SET ready=0')
        with self.assertRaises(StoreError), indexed_view(self.database, None, ['opening'], 'display'):
            pass
        with patch('query_index.build_index', side_effect=RuntimeError('failed dirty rebuild')):
            with self.assertRaises(RuntimeError):
                prepare_indexes(self.database)
        with closing(connect(self.database, writable=True)) as connection:
            self.assertEqual(tuple(connection.execute('SELECT * FROM query_state').fetchone()), before)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='query_search_text'").fetchone())
            self.assertEqual(connection.execute('SELECT ready FROM query_snapshots').fetchone()[0], 0)
        self.assertEqual(prepare_indexes(self.database)['rebuilt_snapshots'], [SAMPLE['snapshot_id']])
        with closing(connect(self.database, writable=True)) as connection:
            connection.execute('DROP INDEX query_search_text')
            connection.execute('UPDATE query_state SET version=3')
        with patch('query_index.build_index', side_effect=AssertionError('ready v3 needs no rebuild')):
            self.assertEqual(prepare_indexes(self.database), {'index_version': VERSION, 'rebuilt_snapshots': []})
            self.assertEqual(prepare_indexes(self.database)['rebuilt_snapshots'], [])
        with indexed_view(self.database, None, ['opening'], 'display') as archive:
            actual = archive.search(search_options({}), SECRET)
        self.assertEqual(actual['results'], search_view(project(SAMPLE, ['opening']), search_options({}), SECRET)['results'])

    def test_bulk_text_index_rebuild_rolls_back_atomically(self):
        with patch('query_index.build_candidates', side_effect=RuntimeError('failed after bulk index build')):
            with self.assertRaises(RuntimeError):
                prepare_indexes(self.database, rebuild=True)
        with closing(connect(self.database)) as connection:
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name='query_search_text'").fetchone())
            self.assertEqual(connection.execute('SELECT ready FROM query_snapshots').fetchone()[0], 1)
        with indexed_view(self.database, None, ['opening'], 'display') as archive:
            actual = archive.search(search_options({}), SECRET)
        expected = search_view(project(SAMPLE, ['opening']), search_options({}), SECRET)
        for key in ('results', 'facets', 'stats'):
            self.assertEqual(actual[key], expected[key])

    def test_scan_reuses_facets_without_narrowing_them_to_matches(self):
        data, _ = workload('long', 300)
        for index, passage in enumerate(data['passages'][32:]):
            passage['text'] = '共用正文 ＡＢＣ "_%" 空\x00白 🙂🚀界'
            passage['speaker_id'] = 'person:student' if index % 2 else 'person:merchant'
        import_snapshot(data, self.database, activate=True)
        snapshot = data['snapshot_id']

        def check_queries():
            for scopes in ([], ['opening'], data['scope_ids']):
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
        updated = next_snapshot(updated, 'scan-facets-parent-restricted')
        updated['withdrawn_ids'].extend([data['entries'][0]['id'], data['sources'][0]['id']])
        import_snapshot(updated, self.database, activate=True)
        check_queries()

    def test_first_facets_use_covering_reads_for_all_record_collections(self):
        data, _ = workload('long', 300)
        import_snapshot(data, self.database, activate=True)
        with indexed_view(self.database, None, ['opening'], 'display') as archive:
            original = archive.visibility_rows
            plans = []

            def observe(sql, parameters=None):
                plans.extend(row[3] for row in archive.connection.execute(
                    'EXPLAIN QUERY PLAN ' + archive.visibility_cte + sql, archive.params))
                return original(sql, parameters)

            with patch.object(archive, 'visibility_rows', side_effect=observe):
                facets = archive.search_facets()
            self.assertEqual(sum(row['n'] for row in facets), len(project(data, ['opening'])['passages']))
            reads = [plan for plan in plans if plan.startswith(('SEARCH q ', 'SCAN q '))]
            self.assertEqual(len(reads), 3)
            self.assertTrue(all('USING COVERING INDEX query_visibility' in plan for plan in reads), reads)

    def test_concurrent_first_facets_share_one_scan(self):
        from indexed_archive import IndexedArchive
        expected = search_view(project(SAMPLE, ['opening']), search_options({}), SECRET)['facets']['speakers']
        barrier = threading.Barrier(10)
        original = IndexedArchive.visibility_rows
        scans = []

        def observe(archive, sql, parameters=None):
            if 'GROUP BY speaker' in sql:
                scans.append(archive.topology_cache_key)
            return original(archive, sql, parameters)

        def request(_):
            with indexed_view(self.database, None, ['opening'], 'display') as archive:
                barrier.wait(timeout=10)
                return [{'value': row['speaker'], 'count': row['n']} for row in archive.search_facets()]

        with patch.object(IndexedArchive, 'visibility_rows', new=observe):
            with ThreadPoolExecutor(max_workers=10) as executor:
                results = list(executor.map(request, range(10)))
        self.assertEqual(results, [expected] * 10)
        self.assertEqual(len(scans), 1)

    def test_visibility_v2_migration_preserves_ready_content_and_postings(self):
        updated = next_snapshot(SAMPLE, 'visibility-migration-restricted')
        updated['withdrawn_ids'] = ['passage:03']
        import_snapshot(updated, self.database, activate=True)
        with closing(connect(self.database, writable=True)) as connection:
            connection.execute('DROP INDEX query_search_text')
            connection.execute('DROP INDEX query_visibility')
            connection.execute('UPDATE query_state SET version=2')
            before = {table: [tuple(row) for row in connection.execute(f'SELECT * FROM {table}')]
                      for table in ('query_records', 'query_postings', 'query_grams', 'query_snapshots')}
            revision = connection.execute('SELECT policy_revision FROM query_state').fetchone()[0]
        old_bytes = self.database.read_bytes()
        with self.assertRaises(StoreError), indexed_view(self.database, None, ['opening'], 'display'):
            pass
        self.assertEqual(self.database.read_bytes(), old_bytes)
        with patch('query_index.build_index', side_effect=AssertionError('no rebuild needed')):
            self.assertEqual(prepare_indexes(self.database), {'index_version': VERSION, 'rebuilt_snapshots': []})
            self.assertEqual(prepare_indexes(self.database)['rebuilt_snapshots'], [])
        with closing(connect(self.database)) as connection:
            self.assertEqual(connection.execute('SELECT policy_revision FROM query_state').fetchone()[0], revision + 1)
            for table, rows in before.items():
                self.assertEqual([tuple(row) for row in connection.execute(f'SELECT * FROM {table}')], rows)
        for snapshot in (SAMPLE['snapshot_id'], updated['snapshot_id']):
            expected = search_view(project(load_snapshot(self.database, snapshot), ['opening']), search_options({}), SECRET)
            with indexed_view(self.database, snapshot, ['opening'], 'display') as archive:
                actual = archive.search(search_options({}), SECRET)
            for key in ('results', 'facets', 'stats'):
                self.assertEqual(actual[key], expected[key])

    def test_visibility_migration_rolls_back_with_failed_dirty_rebuild(self):
        with closing(connect(self.database, writable=True)) as connection:
            connection.execute('DROP INDEX query_search_text')
            connection.execute('DROP INDEX query_visibility')
            connection.execute('UPDATE query_state SET version=2')
            connection.execute('UPDATE query_snapshots SET ready=0')
            state = tuple(connection.execute('SELECT * FROM query_state').fetchone())
        with patch('query_index.build_index', side_effect=RuntimeError('interrupted rebuild')):
            with self.assertRaises(RuntimeError):
                prepare_indexes(self.database)
        with closing(connect(self.database)) as connection:
            self.assertEqual(tuple(connection.execute('SELECT * FROM query_state').fetchone()), state)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='query_visibility'").fetchone())
            self.assertEqual(connection.execute('SELECT ready FROM query_snapshots').fetchone()[0], 0)
        result = prepare_indexes(self.database)
        self.assertEqual(result['rebuilt_snapshots'], [SAMPLE['snapshot_id']])
        with indexed_view(self.database, None, ['opening'], 'display') as archive:
            self.assertTrue(archive.search_facets())

    def assert_search_pages(self, snapshot, query, scopes, limit=50):
        from search_archive import normalize_text
        view = project(load_snapshot(self.database, snapshot), scopes)
        expected = [p for p in ordered_passages(view['passages']) if normalize_text(query) in normalize_text(p['text'])]
        actual = []
        cursor = ''
        while True:
            opts = search_options({'q': [query], 'limit': [str(limit)], 'snapshot': [snapshot],
                                   **({'cursor': [cursor]} if cursor else {})})
            with indexed_view(self.database, snapshot, scopes, 'display') as archive:
                result = archive.search(opts, SECRET)
            self.assertEqual(result['pagination']['total'], len(expected))
            self.assertEqual(result['pagination']['offset'], len(actual))
            actual.extend(result['results'])
            cursor = result['pagination']['next_cursor']
            if not cursor:
                break
        self.assertEqual(actual, expected)

    def test_search_positions_are_isolated_across_reordered_snapshots(self):
        data, _ = workload('long', 300)
        import_snapshot(data, self.database, activate=True)
        updated = next_snapshot(data, 'reordered-search-positions')
        updated['passages'].reverse()
        for index, passage in enumerate(updated['passages']):
            passage['source_locator'] = f'data/samples/story.json#/passages/{index}'
        updated['passages'][0]['text'] = '新快照物资核对'
        import_snapshot(updated, self.database, activate=True)
        for snapshot in (data['snapshot_id'], updated['snapshot_id'], data['snapshot_id']):
            for query in ('', '物资核对', '组号07'):
                self.assert_search_pages(snapshot, query, ['opening'], limit=17)

    def test_retained_snapshot_import_keeps_v4_search_index_incremental(self):
        updated = next_snapshot(SAMPLE, 'retained-v4-incremental')
        updated['passages'][0]['text'] = '新快照正文，旧快照的首尾索引仍需保留。'
        with patch('query_index.install_search_text', side_effect=AssertionError('retained snapshot must not rebuild the shared search index')):
            import_snapshot(updated, self.database, activate=True)

        with closing(connect(self.database)) as connection:
            self.assertIsNotNone(connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='query_search_text'"
            ).fetchone())
            self.assertEqual(connection.execute(
                'SELECT count(*) FROM query_snapshots WHERE ready=1'
            ).fetchone()[0], 2)
        for snapshot in (SAMPLE['snapshot_id'], updated['snapshot_id']):
            expected = search_view(project(load_snapshot(self.database, snapshot), ['opening']),
                                    search_options({'q': ['快照']}), SECRET)
            with indexed_view(self.database, snapshot, ['opening'], 'display') as archive:
                actual = archive.search(search_options({'q': ['快照']}), SECRET)
            self.assertEqual(actual['results'], expected['results'])
            self.assertEqual(actual['pagination']['total'], expected['pagination']['total'])

    def test_dense_search_positions_follow_visible_order_after_withdrawal(self):
        data, _ = workload('linked', 6200)
        import_snapshot(data, self.database, activate=True)
        with indexed_view(self.database, None, ['opening'], 'display') as archive:
            self.assertGreater(len(archive.visible_links()), 5000)
        for query in ('物资核对', '组号07'):
            self.assert_search_pages(data['snapshot_id'], query, ['opening'])
        updated = next_snapshot(data, 'dense-search-restricted')
        updated['withdrawn_ids'] = [data['passages'][index]['id'] for index in (33, 34, 99, 101)]
        import_snapshot(updated, self.database, activate=True)
        for query in ('物资核对', '组号07'):
            self.assert_search_pages(data['snapshot_id'], query, ['opening'])

    def test_search_with_disabled_read_mapping_keeps_literal_results(self):
        data, _ = workload('long', 300)
        data['passages'][32]['text'] = 'ＡＢＣ 空\x00白 🙂🚀界'
        import_snapshot(data, self.database, activate=True)
        view = project(data, ['opening'])
        before = self.database.read_bytes()
        for cap, limit in ((0, 7), (1 << 30, 8)):
            with patch('indexed_archive.READ_MMAP_BYTES', cap):
                for query in ('物资核对', '组号07', 'ＡＢＣ', '空\x00白', '🙂🚀', '文', ''):
                    opts = search_options({'q': [query], 'limit': [str(limit)]})
                    with indexed_view(self.database, None, ['opening'], 'display') as archive:
                        result = archive.search(opts, SECRET)
                        if cap == 0:
                            setting = archive.connection.execute('PRAGMA mmap_size').fetchone()
                            self.assertTrue(setting is None or setting[0] == 0)
                    expected = search_view(view, opts, SECRET)
                    for key in ('results', 'facets', 'stats'):
                        self.assertEqual(result[key], expected[key])
        self.assertEqual(self.database.read_bytes(), before)

    def test_candidate_indexes_migrate_all_snapshots_atomically(self):
        updated = next_snapshot(SAMPLE, 'candidate-migration-new')
        updated['withdrawn_ids'] = ['passage:03']
        updated['sources'][1]['rights']['display'] = 'denied'
        import_snapshot(updated, self.database, activate=True)
        with closing(connect(self.database, writable=True)) as connection:
            connection.execute('DROP TABLE query_postings')
            connection.execute('DROP TABLE query_grams')
            connection.execute('DROP INDEX query_search_text')
            connection.execute('DROP INDEX query_visibility')
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
        self.assertEqual(result['index_version'], VERSION)
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
                    expected_relation = relation_view(view, 'relation:mentor')
                    expected_relation['sources'] = [SAMPLE['sources'][0]]
                    self.assertEqual(archive.relationship('relation:mentor'), expected_relation)

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
