"""Check whether a source audit entry is ready for a requested use.

This gate reads source metadata only. It never downloads or imports source text.
"""
import argparse
import json
from pathlib import Path
import sys


USES = ("collect", "store", "display", "export", "ai_retrieval", "external_ai")
STATUSES = ("pending", "allowed", "limited", "unavailable", "deferred")


class AdmissionError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise AdmissionError(message)


def load_audit(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    require(data.get("schema_version") == "source-audit-0.1", "unsupported source audit schema")
    pages = data.get("pages")
    require(isinstance(pages, list) and pages, "source audit has no pages")
    seen = set()
    for page in pages:
        require(isinstance(page, dict), "source audit page must be an object")
        identifier = page.get("id")
        require(isinstance(identifier, str) and identifier, "source audit page is missing id")
        require(identifier not in seen, f"duplicate source audit page: {identifier}")
        seen.add(identifier)
        require(page.get("admission_status") in STATUSES, f"{identifier}: invalid admission_status")
        allowed = page.get("allowed_uses")
        require(isinstance(allowed, dict) and set(allowed) == set(USES), f"{identifier}: incomplete allowed_uses")
        require(all(value in ("allowed", "unknown", "denied") for value in allowed.values()),
                f"{identifier}: invalid allowed_uses value")
        if page["admission_status"] in ("allowed", "limited"):
            require(isinstance(page.get("authorization_confirmed_by"), str)
                    and page["authorization_confirmed_by"],
                    f"{identifier}: admitted page needs authorization_confirmed_by")
    validate_policy_probe(data.get("follow_up_probe"))
    return data


def validate_policy_probe(probe):
    """Validate policy metadata without treating policy pages as authorization."""
    if probe is None:
        return
    require(isinstance(probe, dict), "follow_up_probe must be an object")
    policy = probe.get("policy_pages_probe")
    if policy is None:
        return
    require(isinstance(policy, dict), "policy_pages_probe must be an object")
    pages = policy.get("pages")
    require(isinstance(pages, list) and pages, "policy_pages_probe has no pages")
    for index, page in enumerate(pages):
        require(isinstance(page, dict), f"policy page {index} must be an object")
        for field in ("url", "title", "summary", "license_scope_finding"):
            require(isinstance(page.get(field), str) and page[field],
                    f"policy page {index} is missing {field}")
        require(page.get("raw_body_saved") is False,
                f"policy page {index} must not save raw body")
    effect = policy.get("admission_effect")
    if effect is None:
        return
    require(isinstance(effect, dict), "policy admission_effect must be an object")
    uses = effect.get("allowed_uses")
    if uses is None:
        return
    require(isinstance(uses, dict) and set(uses) == set(USES),
            "policy admission_effect has incomplete allowed_uses")
    require(all(value in ("unknown", "denied") for value in uses.values()),
            "policy metadata cannot grant source uses")


def evaluate(data, requested_uses, source_id=None):
    pages = [page for page in data["pages"] if source_id is None or page.get("source_id") == source_id]
    if not pages:
        raise AdmissionError("no matching source audit pages")
    results = []
    for page in pages:
        reasons = []
        if page["admission_status"] not in ("allowed", "limited"):
            reasons.append(f"admission_status={page['admission_status']}")
        if not page.get("authorization_confirmed_by"):
            reasons.append("authorization_confirmed_by is missing")
        for use in requested_uses:
            if page["allowed_uses"][use] != "allowed":
                reasons.append(f"{use}={page['allowed_uses'][use]}")
        results.append({"id": page["id"], "source_id": page.get("source_id"),
                        "ready": not reasons, "reasons": reasons})
    return results


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Check source admission from metadata; never imports source text.")
    parser.add_argument("--audit", type=Path, default=root / "data/source-audit.json")
    parser.add_argument("--source-id")
    parser.add_argument("--require", dest="requested_uses", action="append", choices=USES,
                        help="Required use; repeat as needed (default: collect and store)")
    args = parser.parse_args()
    requested = args.requested_uses or ["collect", "store"]
    try:
        data = load_audit(args.audit)
        results = evaluate(data, requested, args.source_id)
        output = {"ready": all(item["ready"] for item in results),
                  "requested_uses": requested, "results": results,
                  "source_text_read": False}
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if output["ready"] else 1
    except (AdmissionError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"ready": False, "error": str(error), "source_text_read": False}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
