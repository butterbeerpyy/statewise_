from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GAP_SLOTS = ROOT / "dataset_design" / "artifacts" / "300_case_gap_slots_current.csv"
DEFAULT_INVENTORY = ROOT / "dataset_design" / "artifacts" / "case_inventory_current.json"
DEFAULT_ARTIFACT_DIR = ROOT / "dataset_design" / "artifacts"

DEFAULT_WAVE_TARGETS = {
    "core_repo_state": 80,
    "memory_lineage_state": 35,
    "clarification_interaction": 20,
    "agent_safety_tool_harm": 15,
}

SUB_BUCKETS = {
    "core_repo_state": [
        ("environment_dependency", 35),
        ("filesystem_semantics", 25),
        ("git_policy", 12),
        ("config_build_test", 8),
    ],
    "memory_lineage_state": [
        ("trusted_but_stale", 15),
        ("same_key_shadowing", 10),
        ("lineage_scope_mismatch", 10),
    ],
    "clarification_interaction": [
        ("missing_premise", 10),
        ("decoy_question", 6),
        ("target_selection", 4),
    ],
    "agent_safety_tool_harm": [
        ("permission_boundary", 5),
        ("prompt_injection", 4),
        ("confused_deputy", 3),
        ("external_tool_state", 3),
    ],
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _cycle_label(index: int, labels: list[tuple[str, int]]) -> str:
    if not labels:
        return "unspecified"
    expanded: list[str] = []
    for label, count in labels:
        expanded.extend([label] * count)
    return expanded[(index - 1) % len(expanded)]


def load_gap_slots(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            rows.append(row)
    return rows


def load_inventory(path: Path) -> dict[str, Any]:
    return _read_json(path)


def pick_wave_slots(
    gap_slots: list[dict[str, Any]],
    targets: dict[str, int],
    wave_id: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in gap_slots:
        grouped[row["bucket"]].append(row)

    selected: list[dict[str, Any]] = []
    for bucket in ("core_repo_state", "memory_lineage_state", "clarification_interaction", "agent_safety_tool_harm"):
        limit = targets[bucket]
        bucket_slots = grouped.get(bucket, [])
        if len(bucket_slots) < limit:
            raise ValueError(f"not enough gap slots in bucket {bucket}: need {limit}, have {len(bucket_slots)}")
        for index, slot in enumerate(bucket_slots[:limit], start=1):
            record = dict(slot)
            record["wave_id"] = wave_id
            record["bucket_rank"] = index
            record["wave_bucket_target"] = limit
            record["recommended_subbucket"] = _cycle_label(index, SUB_BUCKETS[bucket])
            record["status"] = "todo"
            selected.append(record)
    return selected


def build_summary(
    inventory: dict[str, Any],
    selected: list[dict[str, Any]],
    targets: dict[str, int],
) -> dict[str, Any]:
    selected_counts = Counter(row["bucket"] for row in selected)
    quota_gaps = {item["bucket"]: item["gap"] for item in inventory["quota_gaps"]}
    residual_after_wave = {
        bucket: max(0, quota_gaps.get(bucket, 0) - count)
        for bucket, count in targets.items()
    }
    return {
        "schema_version": "statewise-expansion-wave-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "wave_id": "wave1_150",
        "description": "first large production wave for the 300-case expansion",
        "selected_count": len(selected),
        "bucket_counts": dict(sorted(selected_counts.items())),
        "targets": targets,
        "residual_after_wave": residual_after_wave,
        "inventory_snapshot": {
            "parsed_cases": inventory["parsed_cases"],
            "unique_case_ids": inventory["unique_case_ids"],
            "quota_gaps": inventory["quota_gaps"],
            "gap_slot_count": inventory["gap_slot_count"],
        },
        "notes": [
            "This wave is intentionally large to enlarge the target before the first new generation pass.",
            "Slots are prioritized by bucket; the generated list should be handed to case production in order.",
            "The plan does not overwrite existing case JSON files.",
        ],
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "wave_id",
        "bucket",
        "slot_id",
        "bucket_rank",
        "wave_bucket_target",
        "recommended_subbucket",
        "target_domains",
        "source_families",
        "reuse_mode",
        "status",
        "notes",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp"
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gap-slots", default=str(DEFAULT_GAP_SLOTS))
    parser.add_argument("--inventory", default=str(DEFAULT_INVENTORY))
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--wave-id", default="wave1_150")
    parser.add_argument("--total", type=int, default=150)
    args = parser.parse_args()

    gap_slots = load_gap_slots(Path(args.gap_slots).resolve())
    inventory = load_inventory(Path(args.inventory).resolve())
    artifact_dir = Path(args.artifact_dir).resolve()

    if args.total != sum(DEFAULT_WAVE_TARGETS.values()):
        raise SystemExit(
            f"--total must equal {sum(DEFAULT_WAVE_TARGETS.values())} for the first wave"
        )

    selected = pick_wave_slots(gap_slots, DEFAULT_WAVE_TARGETS, args.wave_id)
    summary = build_summary(inventory, selected, DEFAULT_WAVE_TARGETS)
    summary["wave_id"] = args.wave_id

    wave_json = artifact_dir / f"case_expansion_{args.wave_id}.json"
    wave_csv = artifact_dir / f"case_expansion_{args.wave_id}.csv"
    wave_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_csv(wave_csv, selected)

    print(json.dumps({
        "wave_json": str(wave_json),
        "wave_csv": str(wave_csv),
        "selected_count": len(selected),
        "bucket_counts": summary["bucket_counts"],
        "residual_after_wave": summary["residual_after_wave"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
