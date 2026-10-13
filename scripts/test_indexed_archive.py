import json
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from archive_store import StoreError, connect, import_snapshot, load_snapshot
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
            for table in ('query_records', 'query_links', 'query_evidence', 'query_snapshots', 'query_state'):
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


if __name__ == '__main__':
    unittest.main()
