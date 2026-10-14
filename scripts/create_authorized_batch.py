"""Create an empty authorized-batch metadata template from the source audit."""
import argparse
from datetime import date
import json
from pathlib import Path
import sys

from check_source_admission import AdmissionError, USES, load_audit


class TemplateError(ValueError):
    pass


DEFAULT_USES = {
    "bwiki_genshin": ("collect", "store", "display"),
    "miyoushe_obc": ("collect", "store"),
    "kongying_tavern": ("collect", "store", "display"),
}


def build_template(audit, source_id, page_ids, requested_uses=None):
    pages = {page["id"]: page for page in audit["pages"]}
    if source_id not in {page.get("source_id") for page in audit["pages"]}:
        raise TemplateError(f"unknown source_id: {source_id}")
    if not page_ids:
        raise TemplateError("at least one page_id is required")
    if len(page_ids) != len(set(page_ids)):
        raise TemplateError("page_ids must be unique")
    unknown = sorted(set(page_ids) - set(pages))
    if unknown:
        raise TemplateError(f"unknown page_ids: {', '.join(unknown)}")
    wrong_source = [page_id for page_id in page_ids if pages[page_id].get("source_id") != source_id]
    if wrong_source:
        raise TemplateError(f"page_ids do not belong to source_id: {', '.join(wrong_source)}")
    uses = list(requested_uses or DEFAULT_USES.get(source_id, ("collect", "store")))
    if len(uses) != len(set(uses)) or any(use not in USES for use in uses):
        raise TemplateError("requested_uses contains an invalid or duplicate use")
    today = date.today().isoformat()
    return {
        "schema_version": "authorized-batch-0.1",
        "template": True,
        "metadata_only": True,
        "source_text_read": False,
        "batch_id": "",
        "source_id": source_id,
        "authorization_reference": "",
        "authorization_checked_on": "",
        "authorization_scope": "",
        "authorization_valid_until": "",
        "requested_uses": uses,
        "page_ids": page_ids,
        "snapshot_id": "",
        "records": [],
        "template_created_on": today,
        "instructions": "Fill authorization fields and metadata records after written confirmation; do not add source body here.",
    }


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Create an empty authorized batch metadata template; never reads source text.")
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--page-id", action="append", dest="page_ids", required=True,
                        help="Audit page ID; repeat for the first authorized batch")
    parser.add_argument("--require", dest="requested_uses", action="append", choices=USES)
    parser.add_argument("--audit", type=Path, default=root / "data/source-audit.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        audit = load_audit(args.audit)
        template = build_template(audit, args.source_id, args.page_ids, args.requested_uses)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"created": True, "template": True, "metadata_only": True,
                          "source_text_read": False, "output": str(args.output.resolve()),
                          "source_id": args.source_id, "page_count": len(args.page_ids)}, ensure_ascii=False, indent=2))
        return 0
    except (TemplateError, AdmissionError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"created": False, "template": True, "metadata_only": True,
                          "source_text_read": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
