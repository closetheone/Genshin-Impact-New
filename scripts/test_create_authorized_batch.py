import unittest
from pathlib import Path

from check_source_admission import load_audit
from create_authorized_batch import build_template


ROOT = Path(__file__).resolve().parents[1]


class AuthorizedBatchTemplateTests(unittest.TestCase):
    def setUp(self):
        self.audit = load_audit(ROOT / "data/source-audit.json")

    def test_template_keeps_authorization_and_records_empty(self):
        value = build_template(self.audit, "bwiki_genshin", ["audit:bwiki-task"])
        self.assertTrue(value["template"])
        self.assertEqual(value["requested_uses"], ["collect", "store", "display"])
        self.assertEqual(value["records"], [])
        self.assertEqual(value["authorization_reference"], "")
        self.assertFalse(value.get("source_text_read", False))

    def test_template_can_override_requested_uses(self):
        value = build_template(self.audit, "miyoushe_obc", ["audit:obc-guide"], ["collect"])
        self.assertEqual(value["requested_uses"], ["collect"])

    def test_unknown_or_cross_source_page_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown page_ids"):
            build_template(self.audit, "bwiki_genshin", ["missing-page"])
        with self.assertRaisesRegex(ValueError, "do not belong"):
            build_template(self.audit, "bwiki_genshin", ["audit:obc-guide"])

    def test_template_does_not_read_source_body(self):
        value = build_template(self.audit, "kongying_tavern", ["audit:tavern-download"])
        self.assertNotIn("text", value)
        self.assertNotIn("body", value)
        self.assertTrue(value["metadata_only"])
        self.assertFalse(value["source_text_read"])


if __name__ == "__main__":
    unittest.main()
