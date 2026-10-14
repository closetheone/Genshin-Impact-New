import unittest
from pathlib import Path

from check_release_readiness import build_readiness
from check_source_admission import load_audit


ROOT = Path(__file__).resolve().parents[1]


def admitted_audit():
    audit = load_audit(ROOT / "data/source-audit.json")
    for page in audit["pages"]:
        page["admission_status"] = "allowed"
        page["authorization_confirmed_by"] = "Test Owner"
        page["authorization_reference"] = "https://example.invalid/auth"
        page["authorization_checked_on"] = "2026-10-14"
        page["authorization_scope"] = "authorized test batch"
        page["authorization_valid_until"] = "no_expiry"
        page["allowed_uses"] = {use: "allowed" for use in page["allowed_uses"]}
    return audit


def valid_manifest():
    return {
        "schema_version": "authorized-batch-0.1",
        "batch_id": "batch-test-001",
        "source_id": "bwiki_genshin",
        "authorization_reference": "https://example.invalid/auth",
        "authorization_checked_on": "2026-10-14",
        "authorization_scope": "authorized test batch",
        "snapshot_id": "authorized-test-001",
        "requested_uses": ["collect", "store", "display"],
        "page_ids": ["audit:bwiki-chapter"],
        "records": [{"id": "record-001", "source_locator": "https://example.invalid/page#1",
                     "content_type": "game_text_transcript", "revision_id": "rev-001"}],
    }


class ReleaseReadinessTests(unittest.TestCase):
    def test_current_project_is_blocked_without_authorized_batch(self):
        report = build_readiness(load_audit(ROOT / "data/source-audit.json"))
        self.assertFalse(report["ready"])
        self.assertIn("source_admission_not_ready", report["blockers"])
        self.assertIn("authorized_batch_manifest_missing", report["blockers"])
        self.assertFalse(report["source_text_read"])

    def test_admitted_manifest_can_pass_metadata_gate(self):
        report = build_readiness(admitted_audit(), valid_manifest())
        self.assertTrue(report["ready"])
        self.assertEqual(report["blockers"], [])

    def test_invalid_manifest_remains_blocked(self):
        manifest = valid_manifest()
        manifest["records"][0]["text"] = "do not include body"
        report = build_readiness(admitted_audit(), manifest)
        self.assertFalse(report["ready"])
        self.assertTrue(any(item.startswith("authorized_batch_invalid:") for item in report["blockers"]))


if __name__ == "__main__":
    unittest.main()
