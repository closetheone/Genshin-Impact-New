import unittest
from pathlib import Path

from import_sample import guard_import_boundary


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


if __name__ == "__main__":
    unittest.main()
