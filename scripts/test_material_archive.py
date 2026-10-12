from copy import deepcopy
from pathlib import Path
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import uuid
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from archive_store import import_snapshot
from feedback_store import FeedbackConflict, FeedbackRateLimit, read_feedback, submit_feedback
from material_archive import MaterialCapacity, material_view, selection_request
from serve_prototype import PrototypeHandler
from test_graph_archive import SAMPLE, next_snapshot
from validate_sample import SampleError


def request(**changes):
    return selection_request({'snapshot': SAMPLE['snapshot_id'], 'scope_ids': ['opening'], **changes})


def feedback(**changes):
    return {'request_id': str(uuid.uuid4()), 'kind': 'relationship', 'snapshot': SAMPLE['snapshot_id'],
            'reference': 'relation:mentor', 'description': '原创测试：核对证据组', 'contact': 'synthetic@example.invalid', **changes}


class MaterialTests(unittest.TestCase):
    def test_duplicate_occurrences_and_package_contract(self):
        result = material_view(SAMPLE, request(passage_ids=['passage:11', 'passage:11', 'passage:21'], scope_ids=SAMPLE['scope_ids'], topic='核对重复对白'))
        self.assertEqual(result['count'], 2)
        self.assertTrue(result['valid'])
        package = result['package']
        self.assertEqual(len(package['passages']), 2)
        self.assertEqual(package['passages'][0]['text'], package['passages'][1]['text'])
        for key in ('format_version', 'topic', 'language', 'snapshot_id', 'scope_ids', 'sources'):
            self.assertIn(key, package)
        self.assertIn('passage%3A21', result['markdown'])
        self.assertIn('source:fixture', result['markdown'])

    def test_relation_pins_one_complete_group(self):
        result = material_view(SAMPLE, request(add={'kind': 'relationship', 'id': 'relation:mentor'}))
        self.assertEqual(result['count'], 2)
        selection = result['selection']['relationships'][0]
        self.assertEqual(selection['evidence_ids'], ['passage:03', 'passage:04'])
        result = material_view(SAMPLE, request(relationships=[selection], passage_ids=['passage:03'], add={'kind': 'relationship', 'id': 'relation:mentor'}))
        self.assertEqual(result['count'], 2)
        self.assertEqual(len(result['package']['relationships']), 1)
        self.assertEqual(result['package']['relationships'][0]['direction'], 'directed')

    def test_fixed_group_never_silently_switches(self):
        data = deepcopy(SAMPLE); data['withdrawn_ids'] = ['passage:03']
        result = material_view(data, request(scope_ids=SAMPLE['scope_ids'], relationships=[{'id': 'relation:mentor', 'evidence_ids': ['passage:03', 'passage:04']}]))
        self.assertFalse(result['valid']); self.assertIsNone(result['package']); self.assertIsNone(result['markdown'])
        self.assertEqual(result['preview']['passages'], [])
        # A fresh add can select another currently complete group, with explicit new selection.
        fresh = material_view(data, request(scope_ids=SAMPLE['scope_ids'], add={'kind': 'relationship', 'id': 'relation:mentor'}))
        self.assertEqual(fresh['selection']['relationships'][0]['evidence_ids'], ['passage:31'])

    def test_partial_forged_group_rejected(self):
        result = material_view(SAMPLE, request(relationships=[{'id': 'relation:mentor', 'evidence_ids': ['passage:03']}]))
        self.assertFalse(result['valid']); self.assertEqual(result['preview']['passages'], [])

    def test_scope_and_export_and_ai_intersection(self):
        for arguments in [{'passage_ids': ['passage:25']}, {'scope_ids': SAMPLE['scope_ids'], 'passage_ids': ['passage:28']}, {'scope_ids': SAMPLE['scope_ids'], 'add': {'kind': 'relationship', 'id': 'relation:internal-mentor'}}]:
            with self.subTest(arguments=arguments):
                result = material_view(SAMPLE, request(**arguments))
                self.assertFalse(result['valid']); self.assertIsNone(result['package'])
        data = deepcopy(SAMPLE); data['sources'][0]['rights']['external_ai'] = 'denied'
        self.assertFalse(material_view(data, request(purpose='external_ai', passage_ids=['passage:03']))['valid'])
        self.assertTrue(material_view(data, request(purpose='display', passage_ids=['passage:03']))['valid'])
        data['sources'][0]['rights']['display'] = 'denied'
        self.assertFalse(material_view(data, request(passage_ids=['passage:03']))['valid'])

    def test_withdrawals_never_return_hidden_text(self):
        for target in ['passage:03', 'source:fixture', 'person:carpenter', 'entry:bridge']:
            with self.subTest(target=target):
                data = deepcopy(SAMPLE); data['withdrawn_ids'] = [target]
                result = material_view(data, request(passage_ids=['passage:03']))
                self.assertFalse(result['valid']); self.assertNotIn('阿砚是我的徒弟', json.dumps(result, ensure_ascii=False))

    def test_capacity_atomic_full_group(self):
        data = deepcopy(SAMPLE)
        for index in range(50):
            data['passages'].append({**data['passages'][0], 'id': f'passage:extra-{index}', 'source_locator': f"data/samples/story.json#/passages/{32+index}", 'next_ids': []})
        first = [f'passage:extra-{index}' for index in range(49)]
        with self.assertRaises(MaterialCapacity):
            material_view(data, request(passage_ids=first, add={'kind': 'relationship', 'id': 'relation:mentor'}))
        self.assertEqual(len(first), 49)
        result = material_view(data, request(passage_ids=first[:48], add={'kind': 'relationship', 'id': 'relation:mentor'}))
        self.assertEqual(result['count'], 50)
        with self.assertRaises(MaterialCapacity):
            material_view(data, request(passage_ids=first + ['passage:03'], add={'kind': 'passage', 'id': 'passage:04'}))

    def test_bad_request_and_cross_snapshot(self):
        for changes in [{'snapshot': ''}, {'scope_ids': []}, {'scope_ids': ['opening','opening']}, {'purpose': 'other'}, {'topic': 'x'*501}, {'passage_ids': [3]}, {'relationships': [{'id': 'relation:mentor', 'evidence_ids': []}]}, {'add': {'kind': 'unknown', 'id': 'a'}}]:
            with self.subTest(changes=changes), self.assertRaises((SampleError, TypeError)):
                request(**changes)
        with self.assertRaises(SampleError):
            material_view(SAMPLE, request(snapshot='other'))

    def test_markdown_untrusted_text_is_literal(self):
        data = deepcopy(SAMPLE); data['passages'][2]['text'] = '<script>alert(1)</script>\n[unsafe](https://example.invalid)'
        result = material_view(data, request(passage_ids=['passage:03'], topic='<img src=x>'))
        self.assertNotIn('<script>', result['markdown']); self.assertNotIn('[unsafe]', result['markdown'])
        self.assertEqual(result['package']['passages'][0]['text'], data['passages'][2]['text'])


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.inbox = Path(self.temp.name)/'feedback.sqlite3'
    def tearDown(self):
        self.temp.cleanup()

    def test_persistence_private_read_and_idempotency(self):
        payload = feedback(); first = submit_feedback(payload, self.inbox)
        self.assertEqual(first['status'], 'received')
        self.assertTrue(submit_feedback(payload, self.inbox)['duplicate'])
        self.assertEqual(len(read_feedback(self.inbox)), 1)
        self.assertNotIn('contact', read_feedback(self.inbox)[0])
        self.assertEqual(read_feedback(self.inbox, True)[0]['contact'], payload['contact'])
        self.assertEqual(os.stat(self.inbox).st_mode & 0o777, 0o600)
        with self.assertRaises(FeedbackConflict):
            submit_feedback({**payload, 'description': 'changed'}, self.inbox)

    def test_durable_rate_limit_and_retry(self):
        payload = feedback()
        submit_feedback(payload, self.inbox, now=1000)
        for _ in range(4): submit_feedback(feedback(), self.inbox, now=1000)
        with self.assertRaises(FeedbackRateLimit): submit_feedback(feedback(), self.inbox, now=1100)
        self.assertTrue(submit_feedback(payload, self.inbox, now=1100)['duplicate'])
        self.assertEqual(submit_feedback(feedback(), self.inbox, now=1601)['status'], 'received')

    def test_invalid_and_storage_failure(self):
        for changes in [{'description': ' '}, {'kind': 'unknown'}, {'contact': 'x'*201}, {'request_id': 'bad'}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError): submit_feedback(feedback(**changes), self.inbox)
        self.inbox.mkdir()
        with self.assertRaises(OSError): submit_feedback(feedback(), self.inbox)


class MaterialHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.database = Path(self.temp.name)/'archive.sqlite3'
        import_snapshot(SAMPLE, self.database)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), PrototypeHandler); self.server.database = self.database
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()
    def post(self, path, payload, **headers):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        request = Request(self.base + path, data=body, headers={'Content-Type': 'application/json', **headers})
        try: response = urlopen(request)
        except HTTPError as error: response = error
        return response.status, json.load(response)
    def test_material_http_current_policy_on_old_snapshot(self):
        payload = {'snapshot': SAMPLE['snapshot_id'], 'scope_ids': ['opening'], 'passage_ids': ['passage:03']}
        self.assertTrue(self.post('/api/materials', payload)[1]['valid'])
        data = next_snapshot(SAMPLE, 'material-v2'); data['withdrawn_ids'] = ['passage:03']; import_snapshot(data, self.database, activate=True)
        result = self.post('/api/materials', payload)[1]
        self.assertFalse(result['valid']); self.assertIsNone(result['package'])
        self.assertEqual(self.post('/api/materials', {**payload, 'snapshot': 'missing'})[0], 404)
    def test_protocol_and_same_origin(self):
        self.assertEqual(self.post('/api/materials', {}, Origin='https://example.invalid')[0], 403)
        self.assertEqual(self.post('/api/materials', b'{"snapshot":"a","snapshot":"b"}')[0], 400)
        self.assertEqual(self.post('/api/materials', b'{"topic":NaN}')[0], 400)
        self.assertEqual(self.post('/api/materials', b'x'*65537)[0], 413)
        self.assertEqual(self.post('/api/materials', {}, **{'Content-Type':'text/plain'})[0], 400)
        self.assertEqual(self.post('/api/search', {})[0], 405)
    def test_feedback_actual_receipt_rate_limit_and_unavailable(self):
        payload = feedback(); self.assertEqual(self.post('/api/feedback', payload)[0], 200)
        self.assertTrue(self.post('/api/feedback', payload)[1]['duplicate'])
        for _ in range(4): self.assertEqual(self.post('/api/feedback', feedback())[0], 200)
        self.assertEqual(self.post('/api/feedback', feedback())[0], 429)
        inbox = self.database.parent/'feedback.sqlite3'
        self.assertEqual(len(read_feedback(inbox)), 5)
        inbox.unlink(); inbox.mkdir()
        self.assertEqual(self.post('/api/feedback', feedback())[0], 503)
        with self.assertRaises(HTTPError) as error: urlopen(self.base+'/api/feedback')
        self.assertEqual(error.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
