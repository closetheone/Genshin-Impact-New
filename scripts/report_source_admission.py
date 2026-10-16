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


def next_actions(missing_requirements, unapproved_uses, ready):
    if ready:
        return ["准备授权批次元数据并运行 validate_authorized_batch.py。"]
    actions = []
    if "admission_status" in missing_requirements:
        actions.append("取得来源方明确的准入状态确认，并记录可复核授权依据。")
    authorization_fields = {
        "authorization_confirmed_by": "记录授权确认人及身份。",
        "authorization_reference": "记录可复核的邮件、工单或许可链接。",
        "authorization_checked_on": "填写授权核验日期。",
        "authorization_scope": "明确页面、数据集、字段和排除对象范围。",
        "authorization_valid_until": "填写授权有效期或 no_expiry。",
    }
    actions.extend(authorization_fields[field] for field in authorization_fields if field in missing_requirements)
    if unapproved_uses:
        actions.append(f"逐项确认用途：{'、'.join(unapproved_uses)}。")
    return actions or ["复核授权记录和来源范围。"]


def build_report(data, requested_by_source=None, source_filter=None):
    requested_by_source = requested_by_source or DEFAULT_REQUESTS
    source_ids = []
    for page in data["pages"]:
        source_id = page.get("source_id")
        if source_filter and source_id not in source_filter:
            continue
        if source_id not in source_ids:
            source_ids.append(source_id)
    if source_filter:
        missing = sorted(set(source_filter) - set(source_ids))
        if missing:
            raise AdmissionError(f"no matching source audit pages: {', '.join(missing)}")
    sources = []
    for source_id in source_ids:
        pages = [page for page in data["pages"]
                 if page.get("source_id") == source_id
                 and (not source_filter or source_id in source_filter)]
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
        ready = all(item["ready"] for item in results)
        sources.append({
            "source_id": source_id,
            "page_count": len(pages),
            "page_ids": [page["id"] for page in pages],
            "requested_uses": requested,
            "ready": ready,
            "missing_requirements": sorted(set(missing)),
            "unapproved_uses": sorted(unapproved),
            "next_actions": next_actions(sorted(set(missing)), sorted(unapproved), ready),
            "page_results": results,
        })
    return {"ready": all(source["ready"] for source in sources),
            "sources": sources, "source_text_read": False}


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Report source admission gaps from metadata; never reads source text.")
    parser.add_argument("--audit", type=Path, default=root / "data/source-audit.json")
    parser.add_argument("--source-id", action="append", dest="source_ids",
                        help="Limit the report to one or more source IDs; repeat as needed.")
    parser.add_argument("--require", dest="requested_uses", action="append", choices=USES,
                        help="Use the same requested uses for every source; repeat as needed.")
    parser.add_argument("--fail-if-not-ready", action="store_true",
                        help="Return 1 when any selected source is not ready.")
    args = parser.parse_args()
    try:
        data = load_audit(args.audit)
        requested = None
        if args.requested_uses:
            requested = {source_id: tuple(args.requested_uses) for source_id in DEFAULT_REQUESTS}
        report = build_report(data, requested, args.source_ids)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if args.fail_if_not_ready and not report["ready"] else 0
    except (AdmissionError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"ready": False, "error": str(error), "source_text_read": False},
                         ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
