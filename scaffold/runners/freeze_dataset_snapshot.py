from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path

from scaffold.statewise.experiments.experiment_manager import file_sha256, write_atomic


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES_ROOT = ROOT / "scaffold" / "cases"


def build_snapshot(
    base_snapshot,
    batch_index,
    cases_root,
    snapshot_id,
    purpose,
    *,
    delta_only=False,
):
    base_snapshot = Path(base_snapshot).resolve()
    batch_index = Path(batch_index).resolve()
    base = json.loads(base_snapshot.read_text(encoding="utf-8"))
    root = Path(cases_root).resolve()
    base_files = {item["file"] for item in base["cases"]}
    base_ids = {item["case_id"] for item in base["cases"]}
    entries = [] if delta_only else [dict(item) for item in base["cases"]]
    seen_files = {item["file"] for item in entries}
    seen_ids = {item["case_id"] for item in entries}

    with batch_index.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in sorted(rows, key=lambda item: item["case_id"]):
        case_id = row["case_id"].strip()
        filename = f"{case_id}.json"
        if delta_only and (case_id in base_ids or filename in base_files):
            continue
        if not case_id or case_id in seen_ids or filename in seen_files:
            raise ValueError(f"duplicate or empty indexed case: {case_id!r}")
        path = (root / filename).resolve()
        path.relative_to(root)
        case = json.loads(path.read_text(encoding="utf-8"))
        if case.get("case_id") != case_id:
            raise ValueError(f"case_id mismatch in {filename}")
        entries.append({
            "file": filename,
            "case_id": case_id,
            "phase": case.get("phase") or row.get("phase") or None,
            "domain": case.get("domain") or row.get("domain") or None,
            "capability_score_eligible": case.get("capability_score_eligible"),
            "sha256": file_sha256(path),
        })
        seen_files.add(filename)
        seen_ids.add(case_id)

    return {
        "schema_version": "statewise-dataset-snapshot-v1",
        "snapshot_id": snapshot_id,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "purpose": purpose,
        "selection_rule": (
            (
                "Only indexed case_ids absent from frozen base snapshot "
                if delta_only
                else f"Union of frozen base snapshot {base.get('snapshot_id')} and every case_id "
            )
            + f"listed in {batch_index.name}; unrelated directory additions excluded."
        ),
        "case_count": len(entries),
        "base_snapshot": {
            "snapshot_id": base.get("snapshot_id"),
            "sha256": file_sha256(base_snapshot),
            "case_count": len(base["cases"]),
        },
        "batch_index": {
            "file": batch_index.name,
            "sha256": file_sha256(batch_index),
            "case_count": (
                len(entries) if delta_only else len(entries) - len(base["cases"])
            ),
            "source_index_rows": len(rows),
        },
        "notes": [
            "This is a regression/development batch, not a fresh held-out capability set.",
            "Existing capability_score_eligible flags are preserved; missing flags remain null.",
            "StateWise-v1 remains frozen and must not be tuned against these results.",
        ],
        "delta_only": bool(delta_only),
        "cases": entries,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-snapshot", required=True)
    parser.add_argument("--batch-index", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--purpose", required=True)
    parser.add_argument(
        "--delta-only",
        action="store_true",
        help="include only indexed cases absent from the base snapshot",
    )
    parser.add_argument("--cases-root", default=str(DEFAULT_CASES_ROOT))
    args = parser.parse_args()
    snapshot = build_snapshot(
        args.base_snapshot,
        args.batch_index,
        args.cases_root,
        args.snapshot_id,
        args.purpose,
        delta_only=args.delta_only,
    )
    output = Path(args.output).resolve()
    write_atomic(output, snapshot)
    print(json.dumps({
        "output": str(output),
        "snapshot_id": snapshot["snapshot_id"],
        "case_count": snapshot["case_count"],
        "sha256": file_sha256(output),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
