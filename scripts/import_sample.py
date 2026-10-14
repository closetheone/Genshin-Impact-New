import argparse
import json
from pathlib import Path
import sqlite3
import sys

from archive_store import DEFAULT_DATABASE, ROOT, StoreError, import_snapshot


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"Non-finite JSON value: {value}")


def read_sample(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant)


def guard_import_boundary(data, path):
    """Reject source-audit metadata and non-synthetic datasets at the CLI edge."""
    if not isinstance(data, dict):
        raise ValueError("Synthetic importer accepts a JSON object only.")
    if path.name == "source-audit.json" or data.get("schema_version") == "source-audit-0.1" \
            or data.get("record_kind") == "source_metadata" or "pages" in data and "dataset_kind" not in data:
        raise ValueError(
            "Refusing to import source-audit metadata; run report_source_admission.py first, "
            "then provide an admitted synthetic fixture to import_sample.py."
        )
    if data.get("dataset_kind") != "synthetic":
        raise ValueError(
            "Synthetic importer accepts dataset_kind: synthetic only; real sources must first "
            "pass report_source_admission.py and a separate authorized import workflow."
        )
    return data


def main():
    parser = argparse.ArgumentParser(description="Transactionally import synthetic JSON into the local archive; no real game data admission.")
    parser.add_argument("path", nargs="?", type=Path, default=ROOT / "data/samples/story.json")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--activate", action="store_true", help="Activate this snapshot after import; the first snapshot is activated automatically")
    args = parser.parse_args()
    try:
        data = guard_import_boundary(read_sample(args.path), args.path)
        result = import_snapshot(data, args.database, activate=args.activate)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (StoreError, OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
        print(json.dumps({"valid": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
