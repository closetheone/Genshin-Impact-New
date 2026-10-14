import unittest
from pathlib import Path

from check_source_admission import load_audit
from validate_authorized_batch import validate_manifest


ROOT = Path(__file__).resolve().parents[1]


def manifest(**changes):
    value = {
        "schema_version": "authorized-batch-0.1",
        "batch_id": "batch-test-001",
        "source_id": "bwiki_genshin",
        "authorization_reference": "https://example.invalid/authorization/001",
        "authorization_checked_on": "2026-10-14",
        "authorization_scope": "指定任务文本元数据与授权正文批次",
        "snapshot_id": "authorized-test-2026-10-14",
        "requested_uses": ["collect", "store"],
        "page_ids": ["audit:bwiki-chapter"],
        "records": [{
            "id": "source-record:test-001",
            "source_locator": "https://example.invalid/page#record-001",
            "content_type": "game_text_transcript",
            "revision_id": "rev-001",
        }],
    }
    value.update(changes)
    return value


class AuthorizedBatchTests(unittest.TestCase):
    def test_current_pending_sources_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "source admission is not ready"):
            validate_manifest(manifest(), load_audit(ROOT / "data/source-audit.json"))

    def test_admitted_metadata_manifest_is_valid_without_body(self):
        audit = {
            "schema_version": "source-audit-0.1",
            "pages": [{
                "id": "audit:bwiki-chapter", "source_id": "bwiki_genshin",
                "admission_status": "allowed",
                "allowed_uses": {use: "allowed" for use in (
                    "collect", "store", "display", "export", "ai_retrieval", "external_ai")},
                "authorization_confirmed_by": "Test Owner",
                "authorization_reference": "https://example.invalid/authorization/001",
                "authorization_checked_on": "2026-10-14",
                "authorization_scope": "指定任务文本元数据与授权正文批次",
                "authorization_valid_until": "no_expiry",
            }],
        }
        result = validate_manifest(manifest(), audit)
        self.assertTrue(result["valid"])
        self.assertTrue(result["metadata_only"])
        self.assertFalse(result["source_text_read"])

    def test_body_fields_are_rejected(self):
        value = manifest(records=[{"id": "x", "source_locator": "loc", "content_type": "text", "text": "正文"}])
        with self.assertRaisesRegex(ValueError, "source body is not allowed"):
            validate_manifest(value, load_audit(ROOT / "data/source-audit.json"))


if __name__ == "__main__":
    unittest.main()
