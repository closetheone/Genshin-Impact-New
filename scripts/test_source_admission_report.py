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

    def test_report_can_apply_uniform_requested_uses(self):
        data = load_audit(ROOT / 'data/source-audit.json')
        requested = {source_id: ('external_ai',) for source_id in (
            'bwiki_genshin', 'miyoushe_obc', 'kongying_tavern')}
        report = build_report(data, requested)
        self.assertTrue(all(item['requested_uses'] == ['external_ai']
                            for item in report['sources']))
        self.assertTrue(all('external_ai' in item['unapproved_uses']
                            for item in report['sources']))


if __name__ == '__main__':
    unittest.main()
