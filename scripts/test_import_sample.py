import unittest
from pathlib import Path
import tempfile

from archive_store import import_snapshot
from import_sample import guard_import_boundary, read_synthetic_sample


ROOT = Path(__file__).resolve().parents[1]


class ImportBoundaryTests(unittest.TestCase):
    def test_source_audit_is_rejected_before_storage(self):
        audit_path = ROOT / "data/source-audit.json"
        with self.assertRaisesRegex(ValueError, "source-audit metadata"):
            guard_import_boundary({"schema_version": "source-audit-0.1", "pages": []}, audit_path)

    def test_non_synthetic_dataset_is_rejected_before_storage(self):
        with self.assertRaisesRegex(ValueError, "dataset_kind: synthetic"):
            guard_import_boundary({"dataset_kind": "real"}, Path("real.json"))

    def test_synthetic_dataset_reaches_contract_validator(self):
        data = {"dataset_kind": "synthetic", "snapshot_id": "fixture-test"}
        self.assertIs(guard_import_boundary(data, Path("synthetic.json")), data)

    def test_bootstrap_reader_uses_same_synthetic_boundary(self):
        data = read_synthetic_sample(ROOT / "data/samples/story.json")
        self.assertEqual(data["dataset_kind"], "synthetic")

    def test_archive_api_rejects_source_audit_before_database_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "archive.sqlite3"
            with self.assertRaisesRegex(ValueError, "source-audit metadata"):
                import_snapshot({"schema_version": "source-audit-0.1", "pages": []}, database)
            self.assertFalse(database.exists())


if __name__ == "__main__":
    unittest.main()
