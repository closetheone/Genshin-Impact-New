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
                'authorization_reference': 'https://example.invalid/record-1',
                'authorization_checked_on': '2026-10-14',
                'authorization_scope': 'collect and store for test dataset',
                'authorization_valid_until': 'no_expiry',
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
                'authorization_reference': 'https://example.invalid/record-1',
                'authorization_checked_on': '2026-10-14',
                'authorization_scope': 'all test uses',
                'authorization_valid_until': 'no_expiry',
                'allowed_uses': {use: 'allowed' for use in
                                 ('collect', 'store', 'display', 'export', 'ai_retrieval', 'external_ai')},
            }
            path.write_text(json.dumps({'schema_version': 'source-audit-0.1', 'pages': [page]}), encoding='utf-8')
            self.assertTrue(evaluate(load_audit(path), ['collect', 'store', 'external_ai'], 'test')[0]['ready'])

    def test_admitted_page_requires_reproducible_authorization_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'audit.json'
            page = {
                'id': 'audit:test', 'source_id': 'test', 'admission_status': 'allowed',
                'authorization_confirmed_by': 'record-1',
                'allowed_uses': {use: 'allowed' for use in
                                 ('collect', 'store', 'display', 'export', 'ai_retrieval', 'external_ai')},
            }
            path.write_text(json.dumps({'schema_version': 'source-audit-0.1', 'pages': [page]}), encoding='utf-8')
            with self.assertRaises(ValueError) as error:
                load_audit(path)
            self.assertIn('authorization_reference', str(error.exception))

    def test_admitted_page_rejects_non_iso_authorization_date(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'audit.json'
            page = {
                'id': 'audit:test', 'source_id': 'test', 'admission_status': 'allowed',
                'authorization_confirmed_by': 'record-1',
                'authorization_reference': 'https://example.invalid/record-1',
                'authorization_checked_on': '14/10/2026',
                'authorization_scope': 'all test uses',
                'authorization_valid_until': 'no_expiry',
                'allowed_uses': {use: 'allowed' for use in
                                 ('collect', 'store', 'display', 'export', 'ai_retrieval', 'external_ai')},
            }
            path.write_text(json.dumps({'schema_version': 'source-audit-0.1', 'pages': [page]}), encoding='utf-8')
            with self.assertRaises(ValueError) as error:
                load_audit(path)
            self.assertIn('ISO YYYY-MM-DD', str(error.exception))

    def test_admitted_page_rejects_expiry_before_check_date(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'audit.json'
            page = {
                'id': 'audit:test', 'source_id': 'test', 'admission_status': 'allowed',
                'authorization_confirmed_by': 'record-1',
                'authorization_reference': 'https://example.invalid/record-1',
                'authorization_checked_on': '2026-10-14',
                'authorization_scope': 'all test uses',
                'authorization_valid_until': '2026-10-13',
                'allowed_uses': {use: 'allowed' for use in
                                 ('collect', 'store', 'display', 'export', 'ai_retrieval', 'external_ai')},
            }
            path.write_text(json.dumps({'schema_version': 'source-audit-0.1', 'pages': [page]}), encoding='utf-8')
            with self.assertRaises(ValueError) as error:
                load_audit(path)
            self.assertIn('precedes authorization_checked_on', str(error.exception))

    def test_policy_metadata_cannot_grant_source_uses(self):
        data = load_audit(ROOT / 'data/source-audit.json')
        policy = data['follow_up_probe']['policy_pages_probe']
        self.assertTrue(policy['pages'])
        self.assertTrue(policy['repository_license_probe'])
        self.assertTrue(all(page['raw_body_saved'] is False for page in policy['pages']))
        self.assertTrue(all(repo['raw_content_saved'] is False
                            for repo in policy['repository_license_probe']))
        self.assertTrue(all(value in ('unknown', 'denied')
                            for value in policy['admission_effect']['allowed_uses'].values()))

    def test_policy_metadata_rejects_saved_body_or_allowed_use(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'audit.json'
            page = {
                'url': 'https://example.invalid/policy', 'title': 'Policy',
                'summary': 'metadata only', 'license_scope_finding': 'unresolved',
                'raw_body_saved': True,
            }
            audit = {
                'schema_version': 'source-audit-0.1',
                'pages': [{
                    'id': 'audit:test', 'source_id': 'test', 'admission_status': 'pending',
                    'authorization_confirmed_by': None,
                    'allowed_uses': {use: 'unknown' for use in
                                     ('collect', 'store', 'display', 'export', 'ai_retrieval', 'external_ai')},
                }],
                'follow_up_probe': {
                    'policy_pages_probe': {
                        'pages': [page],
                        'admission_effect': {'allowed_uses': {
                            use: 'unknown' for use in
                            ('collect', 'store', 'display', 'export', 'ai_retrieval', 'external_ai')
                        }},
                    }
                },
            }
            path.write_text(json.dumps(audit), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_audit(path)

            page['raw_body_saved'] = False
            audit['follow_up_probe']['policy_pages_probe']['repository_license_probe'] = [{
                'repository': 'example/repo', 'license_url': 'https://example.invalid/LICENSE',
                'license_id': 'MIT', 'license_scope_finding': 'software only',
                'raw_content_saved': True,
            }]
            path.write_text(json.dumps(audit), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_audit(path)

            page['raw_body_saved'] = False
            audit['follow_up_probe']['policy_pages_probe']['admission_effect']['allowed_uses']['display'] = 'allowed'
            path.write_text(json.dumps(audit), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_audit(path)


if __name__ == '__main__':
    unittest.main()
