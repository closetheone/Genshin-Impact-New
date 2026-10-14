"""Validate an authorized source batch manifest without reading source text."""
import argparse
from datetime import date
import json
from pathlib import Path
import sys

from check_source_admission import AdmissionError, USES, evaluate, load_audit


class BatchError(ValueError):
    pass


FORBIDDEN_KEYS = {"text", "body", "content", "raw_body", "html", "markdown"}


def require(condition, message):
    if not condition:
        raise BatchError(message)


def reject_body_fields(value, path="manifest"):
    if isinstance(value, dict):
        for key, child in value.items():
            require(key not in FORBIDDEN_KEYS, f"{path}.{key}: source body is not allowed in a metadata manifest")
            reject_body_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_body_fields(child, f"{path}[{index}]")


def validate_manifest(manifest, audit, audit_path=None):
    require(isinstance(manifest, dict), "manifest must be an object")
    reject_body_fields(manifest)
    require(manifest.get("schema_version") == "authorized-batch-0.1", "unsupported authorized batch schema")
    for field in ("batch_id", "source_id", "authorization_reference", "authorization_scope", "snapshot_id"):
        require(isinstance(manifest.get(field), str) and manifest[field], f"missing {field}")
    try:
        date.fromisoformat(manifest.get("authorization_checked_on", ""))
    except ValueError:
        raise BatchError("authorization_checked_on must be ISO YYYY-MM-DD")
    uses = manifest.get("requested_uses")
    require(isinstance(uses, list) and uses, "requested_uses must be a nonempty list")
    require(len(uses) == len(set(uses)) and all(use in USES for use in uses),
            "requested_uses contains an invalid or duplicate use")
    page_ids = manifest.get("page_ids")
    require(isinstance(page_ids, list) and page_ids and all(isinstance(item, str) and item for item in page_ids),
            "page_ids must be a nonempty list of identifiers")
    records = manifest.get("records")
    require(isinstance(records, list) and records, "records must be a nonempty list")
    for index, record in enumerate(records):
        require(isinstance(record, dict), f"records[{index}] must be an object")
        for field in ("id", "source_locator", "content_type"):
            require(isinstance(record.get(field), str) and record[field],
                    f"records[{index}] is missing {field}")
        if "revision_id" in record:
            require(isinstance(record["revision_id"], str) and record["revision_id"],
                    f"records[{index}].revision_id must be a nonempty string")
    audit_pages = {page["id"]: page for page in audit["pages"]}
    require(all(page_id in audit_pages for page_id in page_ids), "page_ids contains an unknown audit page")
    require(all(audit_pages[page_id].get("source_id") == manifest["source_id"] for page_id in page_ids),
            "page_ids must belong to source_id")
    results = evaluate(audit, uses, manifest["source_id"])
    require(all(item["ready"] for item in results),
            "source admission is not ready for the requested uses; run report_source_admission.py")
    return {
        "valid": True,
        "metadata_only": True,
        "source_text_read": False,
        "batch_id": manifest["batch_id"],
        "source_id": manifest["source_id"],
        "snapshot_id": manifest["snapshot_id"],
        "record_count": len(records),
        "next_step": "Run the data-contract validator on an authorized, separately stored fixture before import.",
    }


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Validate authorized batch metadata; never reads source text.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--audit", type=Path, default=root / "data/source-audit.json")
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        audit = load_audit(args.audit)
        print(json.dumps(validate_manifest(manifest, audit, args.audit), ensure_ascii=False, indent=2))
        return 0
    except (BatchError, AdmissionError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"valid": False, "metadata_only": True, "source_text_read": False,
                          "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
