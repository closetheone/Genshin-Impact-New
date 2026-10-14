import json
from pathlib import Path
import tempfile
import unittest

from check_source_admission import evaluate, load_audit


ROOT = Path(__file__).resolve().parents[1]


class SourceAdmissionTests(unittest.TestCase):
    def test_current_audit_rejects_real_source_collection(self):
        data = load_audit(ROOT / 'data/source-audit.json')
        results = evaluate(data, ['collect', 'store'], 'bwiki_genshin')
        self.assertTrue(results)
        self.assertFalse(any(item['ready'] for item in results))
        self.assertTrue(any('admission_status=pending' in reason
                            for item in results for reason in item['reasons']))

    def test_unknown_use_rejects_even_if_page_is_marked_limited(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'audit.json'
            page = {
                'id': 'audit:test', 'source_id': 'test', 'admission_status': 'limited',
                'authorization_confirmed_by': 'record-1',
                'allowed_uses': {use: 'allowed' for use in
                                 ('collect', 'store', 'display', 'export', 'ai_retrieval', 'external_ai')},
            }
            page['allowed_uses']['external_ai'] = 'unknown'
            path.write_text(json.dumps({'schema_version': 'source-audit-0.1', 'pages': [page]}), encoding='utf-8')
            data = load_audit(path)
            result = evaluate(data, ['collect', 'external_ai'], 'test')[0]
            self.assertFalse(result['ready'])
            self.assertIn('external_ai=unknown', result['reasons'])

    def test_all_requested_uses_need_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'audit.json'
            page = {
                'id': 'audit:test', 'source_id': 'test', 'admission_status': 'allowed',
                'authorization_confirmed_by': 'record-1',
                'allowed_uses': {use: 'allowed' for use in
                                 ('collect', 'store', 'display', 'export', 'ai_retrieval', 'external_ai')},
            }
            path.write_text(json.dumps({'schema_version': 'source-audit-0.1', 'pages': [page]}), encoding='utf-8')
            self.assertTrue(evaluate(load_audit(path), ['collect', 'store', 'external_ai'], 'test')[0]['ready'])


if __name__ == '__main__':
    unittest.main()
