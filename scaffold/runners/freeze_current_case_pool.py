from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from scaffold.statewise.experiments.experiment_manager import file_sha256, write_atomic


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES_ROOT = ROOT / "scaffold" / "cases"
DEFAULT_OUTPUT = ROOT / "scaffold" / "experiments" / "statewise_current_pool_v1.json"


def build_snapshot(cases_root: Path, snapshot_id: str, purpose: str) -> dict:
    entries = []
    seen_ids = set()
    for path in sorted(cases_root.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        case_id = case.get("case_id")
        if not case_id:
            raise ValueError(f"missing case_id: {path.name}")
        if case_id in seen_ids:
            raise ValueError(f"duplicate case_id: {case_id}")
        if path.stem != case_id:
            raise ValueError(f"case_id/file mismatch: {path.name} != {case_id}")
        seen_ids.add(case_id)
        entries.append({
            "file": path.name,
            "case_id": case_id,
            "phase": case.get("phase"),
            "domain": case.get("domain"),
            "quota_bucket": case.get("quota_bucket"),
            "source_family": case.get("source_family"),
            "capability_score_eligible": case.get("capability_score_eligible"),
            "execution_tier": case.get("execution", {}).get("tier"),
            "sha256": file_sha256(path),
        })
    return {
        "schema_version": "statewise-dataset-snapshot-v1",
        "snapshot_id": snapshot_id,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "purpose": purpose,
        "selection_rule": (
            "Every JSON file present in scaffold/cases at freeze time, sorted by "
            "filename. This is a broad development pool, not the final held-out "
            "publication slice."
        ),
        "case_count": len(entries),
        "notes": [
            "The wave1 generated cases are broad target expansion cases.",
            "Use a separately frozen arXiv candidate snapshot for headline reporting.",
            "StateWise-v1 remains frozen; do not tune it against this development pool.",
        ],
        "cases": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases-root", default=str(DEFAULT_CASES_ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--snapshot-id", default="statewise_current_pool_v1")
    parser.add_argument(
        "--purpose",
        default="Broad current SWE-StateBench development pool after wave1 expansion.",
    )
    args = parser.parse_args()

    cases_root = Path(args.cases_root).resolve()
    output = Path(args.output).resolve()
    snapshot = build_snapshot(cases_root, args.snapshot_id, args.purpose)
    write_atomic(output, snapshot)
    print(json.dumps({
        "snapshot": str(output),
        "snapshot_id": snapshot["snapshot_id"],
        "case_count": snapshot["case_count"],
        "sha256": file_sha256(output),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
