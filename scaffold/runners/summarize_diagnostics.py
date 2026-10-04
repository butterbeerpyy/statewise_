from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from scaffold.runners import method_freeze
from scaffold.runners.run_episode_real import _write_atomic
from scaffold.statewise.evaluation import failure_taxonomy


PROJECT_DIR = Path(__file__).resolve().parents[2]
CASES_DIR = PROJECT_DIR / "scaffold" / "cases"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifests", nargs="+")
    parser.add_argument(
        "--output",
        default=str(PROJECT_DIR / "runs" / "diagnostic_summary.json"),
    )
    args = parser.parse_args()
    freeze = method_freeze.verify()
    if not freeze["valid"]:
        raise SystemExit("StateWise-v0 freeze mismatch")

    arm_by_identity = {}
    sources = []
    for manifest_path in args.manifests:
        path = Path(manifest_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        sources.append(str(path.resolve()))
        for record in payload.get("records", []):
            case_id = record["case_id"]
            case = json.loads(
                (CASES_DIR / f"{case_id}.json").read_text(encoding="utf-8")
            )
            raw = record.get("raw_evaluation", {})
            for condition in ("correct", "corrupted", "mitigated"):
                arm = raw.get("arms", {}).get(condition)
                if not arm:
                    continue
                identity = (case_id, record.get("trial", 0), condition)

                arm_by_identity[identity] = failure_taxonomy.build_arm_record(
                        case,
                        condition,
                        arm,
                        method_version=freeze["version"],
                        method_fingerprint=freeze["actual_fingerprint"],
                        api_call_metrics=raw.get(
                            "arm_api_call_metrics", {}
                        ).get(condition, []),
                )

    arm_records = list(arm_by_identity.values())
    now = datetime.now(timezone.utc)
    output = {
        "kind": "statewise_v0_diagnostic_summary",
        "schema_version": failure_taxonomy.SCHEMA_VERSION,
        "created_at": now.isoformat(),
        "method_freeze": freeze,
        "source_manifests": sources,
        "summary": failure_taxonomy.aggregate(arm_records),
        "arm_records": arm_records,
    }
    destination = Path(args.output)
    _write_atomic(destination, output)
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))
    print(f"manifest={destination.resolve()}")


if __name__ == "__main__":
    main()
