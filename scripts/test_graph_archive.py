"""Run with: python3 -m unittest discover -s scripts -p 'test_*.py' -v"""
from copy import deepcopy
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from archive_store import import_snapshot
from graph_archive import GraphUnavailable, character_view, graph_options, graph_view, relation_view
from search_archive import SampleError, StaleCursor, search_options, search_view
from serve_prototype import PrototypeHandler
from validate_sample import project, validate

SAMPLE = json.loads((Path(__file__).resolve().parents[1] / 'data/samples/story.json').read_text())
SECRET = b'graph-test-only-secret'


def options(**kwargs):
    return graph_options({key: [str(value)] for key, value in kwargs.items()})


def large_sample(dense=False):
    data = deepcopy(SAMPLE)
    template = data['characters'][0]
    count = 18 if dense else 125
    people = [{**template, 'id': f'person:test-{index:03}', 'name': f'测试人物{index}'} for index in range(count)]
    data['characters'].extend(people)
    template = data['relationships'][1]
    pairs = [(left, right) for index, left in enumerate(people) for right in people[index+1:]] if dense else [(data['characters'][1], person) for person in people]
    data['relationships'].extend({**template, 'id': f'relation:test-{index:04}', 'from_id': left['id'], 'to_id': right['id']} for index, (left, right) in enumerate(pairs))
    validate(data)
    return data


def next_snapshot(data, identifier):
    data = deepcopy(data)
    data['snapshot_id'] = identifier
    for collection in ('sources', 'characters', 'entries', 'passages', 'relationships'):
        for record in data[collection]:
            record['snapshot_id'] = identifier
    return data


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.view = project(SAMPLE, SAMPLE['scope_ids'])

    def test_opening_bundle_excludes_full_archive(self):
        view = graph_view(project(SAMPLE, ['opening']), options(), SECRET)
        self.assertEqual(len(view['relationships']), 2)
        self.assertEqual(len(view['characters']), 3)
        self.assertEqual(len(view['passages']), 5)
        ids = {passage['id'] for passage in view['passages']}
        self.assertTrue(all(set(passage['next_ids']) <= ids for passage in view['passages']))
        self.assertNotIn('relation:parent', str(view))

    def test_evidence_and_direction(self):
        detail = relation_view(self.view, 'relation:mentor')
        relation = detail['relationships'][0]
        self.assertEqual((relation['from_id'], relation['to_id'], relation['direction']), ('person:carpenter', 'person:student', 'directed'))
        self.assertEqual(relation['evidence_groups'], [['passage:03', 'passage:04'], ['passage:31']])
        self.assertEqual({p['id'] for p in detail['passages']}, {'passage:03', 'passage:04', 'passage:31'})

    def test_incomplete_group_and_pending_rejected(self):
        for identifier in ('relation:parent', 'relation:unverified', 'missing'):
            with self.subTest(identifier=identifier), self.assertRaises(GraphUnavailable):
                relation_view(project(SAMPLE, ['opening']), identifier)

    def test_alternative_group_survives(self):
        data = deepcopy(SAMPLE); data['withdrawn_ids'] = ['passage:03']
        relation = relation_view(project(data, data['scope_ids']), 'relation:mentor')['relationships'][0]
        self.assertEqual(relation['evidence_groups'], [['passage:31']])

    def test_hops_and_predicate(self):
        narrow = graph_view(self.view, options(center='person:carpenter', hops=1), SECRET)
        wide = graph_view(self.view, options(center='person:carpenter', hops=2), SECRET)
        self.assertEqual(len(narrow['characters']), 3)
        self.assertEqual(len(wide['characters']), 4)
        mentors = graph_view(self.view, options(predicate='mentor_of', hops=2), SECRET)
        self.assertEqual([r['id'] for r in mentors['relationships']], ['relation:mentor'])

    def test_story_conditions_exact_match(self):
        for condition, expected in [('east', ['relation:east-opposition']), ('west', ['relation:west-partners']), ('later', ['relation:internal-mentor'])]:
            with self.subTest(condition=condition):
                result = graph_view(self.view, options(center='person:merchant', condition=condition, hops=2), SECRET)
                self.assertEqual([r['id'] for r in result['relationships']], expected)
        opening = graph_view(self.view, options(condition='opening'), SECRET)
        self.assertTrue(all(r['branch_id'] is None and r['required_scope_ids'] == ['opening'] for r in opening['relationships']))

    def test_unavailable_center_and_empty_graph(self):
        with self.assertRaises(GraphUnavailable):
            graph_view(self.view, options(center='missing'), SECRET)
        result = graph_view(project(SAMPLE, ['opening']), options(center='person:merchant'), SECRET)
        self.assertEqual(len(result['characters']), 1)
        self.assertEqual(result['relationships'], [])

    def test_export_revision_and_internal_evidence(self):
        query = options(hops=2)
        displayed = graph_view(self.view, query, SECRET)
        exported = graph_view(project(SAMPLE, SAMPLE['scope_ids'], 'export'), query, SECRET)
        self.assertNotEqual(displayed['content_revision'], exported['content_revision'])
        self.assertNotIn('passage:28', str(exported))
        self.assertEqual(graph_view(project(SAMPLE, ['opening']), query, SECRET)['content_revision'], graph_view(project(SAMPLE, ['opening'], 'export'), query, SECRET)['content_revision'])

    def test_revision_detects_loss_of_alternative_group(self):
        before = graph_view(self.view, options(), SECRET)
        data = deepcopy(SAMPLE); data['withdrawn_ids'] = ['passage:31']
        after = graph_view(project(data, data['scope_ids']), options(), SECRET)
        self.assertEqual([r['id'] for r in before['relationships']], [r['id'] for r in after['relationships']])
        self.assertNotEqual(before['content_revision'], after['content_revision'])

    def traverse(self, data, center):
        view = project(data, ['opening'])
        query = options(center=center)
        result = graph_view(view, query, SECRET)
        seen = []
        while True:
            self.assertLessEqual(len(result['characters']), 50)
            self.assertLessEqual(len(result['relationships']), 100)
            self.assertTrue(result['truncated'])
            node_ids = {node['id'] for node in result['characters']}
            self.assertIn(center, node_ids)
            self.assertTrue(all({r['from_id'], r['to_id']} <= node_ids for r in result['relationships']))
            seen.extend(r['id'] for r in result['relationships'])
            if not result['pagination']['next_cursor']:
                break
            query['cursor'] = result['pagination']['next_cursor']
            result = graph_view(view, query, SECRET)
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(len(seen), result['pagination']['total_relationships'])
        self.assertIsNotNone(result['pagination']['previous_cursor'])
        restored = graph_view(view, options(center=center, page=result['pagination']['page'], snapshot=data['snapshot_id']), SECRET)
        self.assertEqual(restored['content_revision'], result['content_revision'])
        return view

    def test_node_limit_continuation(self):
        self.traverse(large_sample(), 'person:student')

    def test_edge_limit_continuation(self):
        self.traverse(large_sample(True), 'person:test-000')

    def test_cursor_binds_query_snapshot_boundary_and_process(self):
        data = large_sample(); view = project(data, ['opening']); query = options()
        cursor = graph_view(view, query, SECRET)['pagination']['next_cursor']
        for field, value in [('center', 'person:helper'), ('hops', 2), ('predicate', 'mentor_of'), ('condition', 'opening')]:
            with self.subTest(field=field), self.assertRaises(SampleError):
                graph_view(view, {**query, field: value, 'cursor': cursor}, SECRET)
        for field, value in [('snapshot_id', 'another'), ('scope_ids', ['opening', 'later']), ('purpose', 'export')]:
            with self.subTest(field=field), self.assertRaises(SampleError):
                graph_view({**view, field: value}, {**query, 'cursor': cursor}, SECRET)
        with self.assertRaises(SampleError):
            graph_view(view, {**query, 'cursor': cursor}, b'restarted')
        with self.assertRaises(SampleError):
            graph_view(view, {**query, 'cursor': cursor[:-1] + ('1' if cursor[-1] != '1' else '2')}, SECRET)

    def test_cursor_stale_on_withdrawal(self):
        data = large_sample(); query = options(); view = project(data, ['opening'])
        cursor = graph_view(view, query, SECRET)['pagination']['next_cursor']
        data['withdrawn_ids'] = ['passage:06']
        with self.assertRaises(StaleCursor):
            graph_view(project(data, ['opening']), {**query, 'cursor': cursor}, SECRET)

    def test_parameter_validation(self):
        for field, value in [('hops', '3'), ('hops', '0'), ('predicate', 'unknown'), ('condition', 'unknown'), ('center', ''), ('center', 'x'*161), ('page', '0'), ('page', '-1'), ('page', '1.5'), ('page', '999999'), ('cursor', '')]:
            with self.subTest(field=field, value=value), self.assertRaises(SampleError):
                graph_options({field: [value]})
        for field in ('center', 'hops', 'predicate', 'condition', 'page', 'cursor'):
            with self.subTest(field=field), self.assertRaises(SampleError):
                graph_options({field: ['1', '1']})
        with self.assertRaises(SampleError):
            options(page=2)

    def test_character_search_identity_and_boundary(self):
        result = character_view(self.view, '青禾')
        self.assertEqual({c['id'] for c in result['characters']}, {'person:carpenter', 'person:merchant'})
        data = deepcopy(SAMPLE); data['withdrawn_ids'] = ['person:merchant']
        self.assertEqual(len(character_view(project(data, ['opening']), '青禾')['characters']), 1)
        self.assertTrue(character_view(project(large_sample(), ['opening']), '')['truncated'])
        with self.assertRaises(SampleError):
            character_view(self.view, 'x'*161)

    def test_existing_search_regression(self):
        result = search_view(self.view, search_options({'q': ['先核对物资']}), SECRET)
        self.assertEqual(result['pagination']['total'], 2)
        self.assertEqual({r['id'] for r in result['results']}, {'passage:11', 'passage:21'})


class GraphHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / 'archive.sqlite3'
        import_snapshot(SAMPLE, self.database)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), PrototypeHandler)
        self.server.database = self.database; self.server.cursor_secret = SECRET
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def get(self, path, **parameters):
        params = {'scope': ['opening'], **parameters}
        try:
            response = urlopen(self.base + path + '?' + urlencode(params, doseq=True))
        except HTTPError as error:
            response = error
        return response.status, json.load(response)

    def test_endpoints_and_errors(self):
        status, graph = self.get('/api/graph'); self.assertEqual(status, 200); self.assertEqual(graph['storage'], 'sqlite')
        self.assertEqual(self.get('/api/relationship', id='relation:mentor')[0], 200)
        self.assertEqual(self.get('/api/relationship', id='relation:parent')[0], 404)
        self.assertEqual(self.get('/api/characters', q='青禾')[1]['characters'][0]['name'], '青禾')
        status, roster = self.get('/api/characters', q='', limit='100')
        self.assertEqual(status, 200)
        self.assertEqual(len(roster['characters']), 4)
        self.assertFalse(roster['truncated'])
        for path, params in [('/api/graph', {'unknown': 'x'}), ('/api/graph', {'hops': ['1', '2']}), ('/api/graph', {'scope': []}), ('/api/relationship', {'id': ['a', 'b']}), ('/api/relationship', {}), ('/api/characters', {'q': ['a', 'b']})]:
            with self.subTest(path=path, params=params):
                self.assertEqual(self.get(path, **params)[0], 400)
        self.assertEqual(self.get('/api/characters', limit='201')[0], 400)
        self.assertEqual(self.get('/api/graph', snapshot='missing')[0], 404)
        self.assertEqual(self.get('/api/graph', center='missing')[1]['code'], 'graph_unavailable')

    def test_status_exposes_source_admission_metadata_only(self):
        status, payload = self.get('/api/status')
        self.assertEqual(status, 200)
        admission = payload['source_admission']
        self.assertFalse(admission['ready'])
        self.assertFalse(admission['source_text_read'])
        self.assertEqual({item['source_id'] for item in admission['sources']},
                         {'bwiki_genshin', 'miyoushe_obc', 'kongying_tavern'})

    def test_old_snapshot_enforces_new_withdrawal_and_rights(self):
        before = self.get('/api/graph')[1]
        data = next_snapshot(SAMPLE, 'withdrawn-v2'); data['withdrawn_ids'] = ['passage:06']
        import_snapshot(data, self.database, activate=True)
        after = self.get('/api/graph', snapshot=SAMPLE['snapshot_id'])[1]
        self.assertEqual(after['snapshot_id'], SAMPLE['snapshot_id'])
        self.assertEqual(len(after['relationships']), 1)
        self.assertNotEqual(before['content_revision'], after['content_revision'])
        self.assertEqual(self.get('/api/relationship', id='relation:bridge-partners', snapshot=SAMPLE['snapshot_id'])[0], 404)
        data = next_snapshot(data, 'denied-v3'); data['sources'][0]['rights']['export'] = 'denied'
        import_snapshot(data, self.database)
        self.assertEqual(self.get('/api/graph', snapshot=SAMPLE['snapshot_id'], purpose='export')[0], 404)
        self.assertEqual(self.get('/api/characters', snapshot=SAMPLE['snapshot_id'], purpose='export')[1]['characters'], [])

    def test_signed_continuation_lifecycle(self):
        data = next_snapshot(large_sample(), 'large-v2'); import_snapshot(data, self.database, activate=True)
        first = self.get('/api/graph')[1]
        args = {'snapshot': data['snapshot_id'], 'cursor': first['pagination']['next_cursor']}
        status, second = self.get('/api/graph', **args)
        self.assertEqual(status, 200); self.assertEqual(second['query']['page'], 2)
        self.assertEqual(self.get('/api/graph', cursor=args['cursor'])[0], 400)
        updated = next_snapshot(data, 'large-v3'); updated['withdrawn_ids'] = ['passage:06']; import_snapshot(updated, self.database, activate=True)
        self.assertEqual(self.get('/api/graph', **args)[0], 409)
        self.assertEqual(self.get('/api/graph', snapshot=data['snapshot_id'], page=1)[0], 200)
        self.server.cursor_secret = secrets.token_bytes(32)
        self.assertEqual(self.get('/api/graph', **args)[0], 400)

    def test_reader_pagination_requires_fixed_snapshot_and_boundary(self):
        data = next_snapshot(SAMPLE, 'reader-v2')
        for index in range(32, 100):
            data['passages'].append({**data['passages'][0], 'id': f'passage:reader-{index:03}',
                                     'text': f'阅读分页测试 {index}', 'source_locator': f'data/samples/story.json#/passages/{index}',
                                     'next_ids': []})
        validate(data)
        import_snapshot(data, self.database, activate=True)
        status, first = self.get('/api/read', id='passage:03')
        self.assertEqual(status, 200)
        self.assertEqual(first['target_id'], 'passage:03')
        cursor = first['pagination']['next_cursor']
        self.assertIsNotNone(cursor)
        self.assertEqual(self.get('/api/read', cursor=cursor, id='passage:03')[0], 400)
        args = {'snapshot': data['snapshot_id'], 'id': 'passage:03', 'cursor': cursor}
        status, second = self.get('/api/read', **args)
        self.assertEqual(status, 200)
        self.assertIsNone(second['target_id'])
        self.assertNotEqual(first['passages'][0]['id'], second['passages'][0]['id'])
        self.assertLessEqual(len(first['passages']), 50)
        self.assertEqual(self.get('/api/read', **{**args, 'purpose': 'export'})[0], 400)
        updated = next_snapshot(data, 'reader-v3')
        updated['withdrawn_ids'] = ['passage:03']
        import_snapshot(updated, self.database)
        self.assertEqual(self.get('/api/read', **args)[0], 409)
        self.assertEqual(self.get('/api/read', snapshot=data['snapshot_id'], id='passage:03')[0], 404)


if __name__ == '__main__':
    unittest.main()
