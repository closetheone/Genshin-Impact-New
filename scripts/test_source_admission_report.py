import unittest
from pathlib import Path

from check_source_admission import load_audit
from report_source_admission import build_report


ROOT = Path(__file__).resolve().parents[1]


class SourceAdmissionReportTests(unittest.TestCase):
    def test_report_groups_current_sources_and_stays_blocked(self):
        report = build_report(load_audit(ROOT / 'data/source-audit.json'))
        self.assertFalse(report['ready'])
        self.assertFalse(report['source_text_read'])
        self.assertEqual({item['source_id'] for item in report['sources']},
                         {'bwiki_genshin', 'miyoushe_obc', 'kongying_tavern'})
        self.assertTrue(all(not item['ready'] for item in report['sources']))

    def test_report_exposes_missing_authorization_fields(self):
        report = build_report(load_audit(ROOT / 'data/source-audit.json'))
        for source in report['sources']:
            self.assertIn('admission_status', source['missing_requirements'])
            self.assertIn('authorization_confirmed_by', source['missing_requirements'])
            self.assertTrue(source['unapproved_uses'])
            self.assertTrue(source['next_actions'])

    def test_ready_report_exposes_batch_next_action(self):
        data = load_audit(ROOT / 'data/source-audit.json')
        for page in data['pages']:
            page['admission_status'] = 'allowed'
            page['authorization_confirmed_by'] = 'Test Owner'
            page['authorization_reference'] = 'https://example.invalid/auth'
            page['authorization_checked_on'] = '2026-10-14'
            page['authorization_scope'] = 'test scope'
            page['authorization_valid_until'] = 'no_expiry'
            page['allowed_uses'] = {use: 'allowed' for use in page['allowed_uses']}
        report = build_report(data)
        self.assertTrue(report['ready'])
        self.assertTrue(all(item['next_actions'] == ['准备授权批次元数据并运行 validate_authorized_batch.py。']
                            for item in report['sources']))

    def test_report_can_apply_uniform_requested_uses(self):
        data = load_audit(ROOT / 'data/source-audit.json')
        requested = {source_id: ('external_ai',) for source_id in (
            'bwiki_genshin', 'miyoushe_obc', 'kongying_tavern')}
        report = build_report(data, requested)
        self.assertTrue(all(item['requested_uses'] == ['external_ai']
                            for item in report['sources']))
        self.assertTrue(all('external_ai' in item['unapproved_uses']
                            for item in report['sources']))

    def test_report_can_filter_one_source(self):
        data = load_audit(ROOT / 'data/source-audit.json')
        report = build_report(data, source_filter=['kongying_tavern'])
        self.assertFalse(report['ready'])
        self.assertEqual([item['source_id'] for item in report['sources']], ['kongying_tavern'])

    def test_report_rejects_unknown_source_filter(self):
        data = load_audit(ROOT / 'data/source-audit.json')
        with self.assertRaises(ValueError):
            build_report(data, source_filter=['unknown_source'])


if __name__ == '__main__':
    unittest.main()
