"""Report source admission gaps from metadata only."""
import argparse
import json
from pathlib import Path
import sys

from check_source_admission import AdmissionError, USES, evaluate, load_audit


DEFAULT_REQUESTS = {
    "bwiki_genshin": ("collect", "store", "display"),
    "miyoushe_obc": ("collect", "store"),
    "kongying_tavern": ("collect", "store", "display"),
}


def build_report(data, requested_by_source=None):
    requested_by_source = requested_by_source or DEFAULT_REQUESTS
    source_ids = []
    for page in data["pages"]:
        source_id = page.get("source_id")
        if source_id not in source_ids:
            source_ids.append(source_id)
    sources = []
    for source_id in source_ids:
        pages = [page for page in data["pages"] if page.get("source_id") == source_id]
        requested = list(requested_by_source.get(source_id, ("collect", "store")))
        results = evaluate(data, requested, source_id)
        missing = []
        unapproved = set()
        for page in pages:
            if page.get("admission_status") not in ("allowed", "limited"):
                missing.append("admission_status")
            for field in ("authorization_confirmed_by", "authorization_reference",
                          "authorization_checked_on", "authorization_scope",
                          "authorization_valid_until"):
                if not page.get(field):
                    missing.append(field)
            unapproved.update(use for use in requested
                             if page.get("allowed_uses", {}).get(use) != "allowed")
        sources.append({
            "source_id": source_id,
            "page_count": len(pages),
            "requested_uses": requested,
            "ready": all(item["ready"] for item in results),
            "missing_requirements": sorted(set(missing)),
            "unapproved_uses": sorted(unapproved),
            "page_results": results,
        })
    return {"ready": all(source["ready"] for source in sources),
            "sources": sources, "source_text_read": False}


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Report source admission gaps from metadata; never reads source text.")
    parser.add_argument("--audit", type=Path, default=root / "data/source-audit.json")
    parser.add_argument("--require", dest="requested_uses", action="append", choices=USES,
                        help="Use the same requested uses for every source; repeat as needed.")
    args = parser.parse_args()
    try:
        data = load_audit(args.audit)
        requested = None
        if args.requested_uses:
            requested = {source_id: tuple(args.requested_uses) for source_id in DEFAULT_REQUESTS}
        print(json.dumps(build_report(data, requested), ensure_ascii=False, indent=2))
        return 0
    except (AdmissionError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"ready": False, "error": str(error), "source_text_read": False},
                         ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
