"""Check whether the real-data release gate has enough authorization metadata."""
import argparse
import json
from pathlib import Path
import sys

from check_source_admission import AdmissionError, load_audit
from report_source_admission import build_report
from validate_authorized_batch import BatchError, validate_manifest


def build_readiness(audit, manifest=None):
    admission = build_report(audit)
    blockers = []
    if not admission["ready"]:
        blockers.append("source_admission_not_ready")
    batch = None
    if manifest is None:
        blockers.append("authorized_batch_manifest_missing")
    else:
        try:
            batch = validate_manifest(manifest, audit)
        except (BatchError, AdmissionError, ValueError, TypeError, KeyError) as error:
            blockers.append(f"authorized_batch_invalid: {error}")
    return {
        "ready": not blockers,
        "release_scope": "real_source_page",
        "source_text_read": False,
        "blockers": blockers,
        "source_admission": admission,
        "authorized_batch": batch,
        "next_steps": [
            "取得并记录来源方的逐项用途授权。",
            "生成并补齐 authorized-batch-0.1 元数据清单。",
            "通过正文数据契约、出处、分支和关系证据核验后再导入。",
        ] if blockers else [
            "运行数据契约校验和完整回归测试，再安排真实页面灰度开放。",
        ],
    }


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Check real-data release readiness from metadata; never reads source text.")
    parser.add_argument("--audit", type=Path, default=root / "data/source-audit.json")
    parser.add_argument("--manifest", type=Path, help="Authorized batch metadata manifest")
    parser.add_argument("--fail-if-not-ready", action="store_true")
    args = parser.parse_args()
    try:
        audit = load_audit(args.audit)
        manifest = json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest else None
        report = build_readiness(audit, manifest)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if args.fail_if_not_ready and not report["ready"] else 0
    except (AdmissionError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"ready": False, "release_scope": "real_source_page",
                          "source_text_read": False, "blockers": [str(error)]}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
