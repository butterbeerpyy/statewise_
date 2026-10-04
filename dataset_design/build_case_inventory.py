from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_ROOT = ROOT / "scaffold" / "cases"
DEFAULT_QUOTA = ROOT / "dataset_design" / "artifacts" / "300_case_source_quota.csv"
DEFAULT_ARTIFACT_DIR = ROOT / "dataset_design" / "artifacts"

CORE_DOMAINS = {
    "environment_state",
    "filesystem_state",
    "user_private_semantics",
    "git_state",
    "database_state",
    "deployment_state",
    "config_state",
    "build_test_state",
}

CONTROL_DOMAINS = {
    "read_only_control",
}

MEMORY_STRESSORS = {
    "IMPLICIT_CONFLICT",
    "SAME_KEY_CONFLICT",
    "STALE_VALUE",
    "STALE_PLAN",
    "OVER_GENERALIZATION",
}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _source_repository(case: dict[str, Any]) -> str | None:
    reference = case.get("source_reference")
    if isinstance(reference, dict):
        value = reference.get("repository")
        return str(value) if value else None
    if isinstance(reference, str):
        return reference
    return None


def _difficulty(case: dict[str, Any], key: str) -> str | None:
    difficulty = case.get("difficulty")
    if isinstance(difficulty, dict):
        value = difficulty.get(key)
        return str(value) if value is not None else None
    return None


def infer_quota_bucket(case: dict[str, Any]) -> str:

    explicit = case.get("quota_bucket")
    if explicit:
        return str(explicit)
    if case.get("canary_only"):
        return "measurement_canary"
    domain = case.get("domain")
    if domain in CONTROL_DOMAINS:
        return "control_or_excluded"
    if domain in CORE_DOMAINS:
        return "core_repo_state"
    return "unassigned"


def case_record(path: Path, case: dict[str, Any]) -> dict[str, Any]:
    corruption = case.get("corruption_operator")
    domain = str(case.get("domain") or "")
    return {
        "file": path.name,
        "case_id": str(case.get("case_id") or ""),
        "phase": case.get("phase"),
        "domain": domain or None,
        "quota_bucket": infer_quota_bucket(case),
        "execution_tier": (case.get("execution") or {}).get("tier"),
        "canary_only": bool(case.get("canary_only")),
        "capability_score_eligible": case.get("capability_score_eligible"),
        "source_repository": _source_repository(case),
        "source_family": case.get("source_family"),
        "corruption_operator": corruption,
        "observability": _difficulty(case, "observability"),
        "causal_depth": _difficulty(case, "causal_depth"),
        "impact": _difficulty(case, "impact"),
        "persistence": _difficulty(case, "persistence"),
        "memory_lineage_stressor": (
            corruption in MEMORY_STRESSORS
            or "memory" in domain
            or "lineage" in domain
        ),
    }


def load_cases(cases_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for path in sorted(cases_root.glob("*.json")):
        try:
            case = _read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append({
                "file": path.name,
                "kind": type(exc).__name__,
                "detail": str(exc),
            })
            continue
        record = case_record(path, case)
        if record["case_id"] != path.stem:
            errors.append({
                "file": path.name,
                "kind": "case_id_filename_mismatch",
                "detail": str(record["case_id"]),
            })
        records.append(record)
    return records, errors


def load_quota(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            bucket = (row.get("bucket") or "").strip()
            if not bucket or bucket == "TOTAL":
                continue
            rows.append({
                **row,
                "bucket": bucket,
                "quota": int(row.get("quota") or 0),
            })
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp"
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})
    temporary.replace(path)


def build_summary(records: list[dict[str, Any]], errors: list[dict[str, str]], quota_rows):
    case_ids = [record["case_id"] for record in records]
    duplicate_ids = sorted(case_id for case_id, n in Counter(case_ids).items() if n > 1)
    by_bucket = Counter(record["quota_bucket"] for record in records)
    by_domain = Counter(record["domain"] or "<missing>" for record in records)
    by_phase = Counter(record["phase"] or "<missing>" for record in records)
    by_tier = Counter(record["execution_tier"] or "<missing>" for record in records)
    by_eligible = Counter(str(record["capability_score_eligible"]) for record in records)
    memory_stressor_cases = sum(bool(record["memory_lineage_stressor"]) for record in records)

    gaps = []
    gap_slots = []
    for row in quota_rows:
        bucket = row["bucket"]
        current = by_bucket.get(bucket, 0)
        target = row["quota"]
        gap = max(0, target - current)
        gaps.append({
            "bucket": bucket,
            "current": current,
            "quota": target,
            "gap": gap,
            "target_domains": row.get("target_domains"),
            "source_families": row.get("source_families"),
            "reuse_mode": row.get("reuse_mode"),
        })
        for index in range(1, gap + 1):
            gap_slots.append({
                "slot_id": f"{bucket}_{index:03d}",
                "bucket": bucket,
                "target_domains": row.get("target_domains"),
                "source_families": row.get("source_families"),
                "reuse_mode": row.get("reuse_mode"),
                "status": "todo",
                "notes": row.get("notes"),
            })

    return {
        "schema_version": "statewise-case-inventory-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_files": len(records) + len(errors),
        "parsed_cases": len(records),
        "unique_case_ids": len(set(case_ids)),
        "duplicate_case_ids": duplicate_ids,
        "errors": errors,
        "counts": {
            "by_quota_bucket": dict(sorted(by_bucket.items())),
            "by_domain": dict(sorted(by_domain.items())),
            "by_phase": dict(sorted(by_phase.items())),
            "by_execution_tier": dict(sorted(by_tier.items())),
            "by_capability_score_eligible": dict(sorted(by_eligible.items())),
            "memory_lineage_stressor_cases": memory_stressor_cases,
        },
        "quota_gaps": gaps,
        "gap_slot_count": len(gap_slots),
        "notes": [
            "Canary and control cases are not counted toward the 300-case quota.",
            "Existing operational software-state cases are conservatively counted as core_repo_state unless quota_bucket is explicit.",
            "Missing capability_score_eligible should be resolved before any formal publication table.",
        ],
    }, gap_slots


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases-root", default=str(DEFAULT_CASES_ROOT))
    parser.add_argument("--quota", default=str(DEFAULT_QUOTA))
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--prefix", default="current")
    args = parser.parse_args()

    cases_root = Path(args.cases_root).resolve()
    quota_path = Path(args.quota).resolve()
    artifact_dir = Path(args.artifact_dir).resolve()

    records, errors = load_cases(cases_root)
    quota_rows = load_quota(quota_path)
    summary, gap_slots = build_summary(records, errors, quota_rows)

    artifact_dir.mkdir(parents=True, exist_ok=True)
    inventory_json = artifact_dir / f"case_inventory_{args.prefix}.json"
    inventory_csv = artifact_dir / f"case_inventory_{args.prefix}.csv"
    gap_csv = artifact_dir / f"300_case_gap_slots_{args.prefix}.csv"

    inventory_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_csv(inventory_csv, records, [
        "case_id",
        "file",
        "phase",
        "domain",
        "quota_bucket",
        "execution_tier",
        "canary_only",
        "capability_score_eligible",
        "source_repository",
        "source_family",
        "corruption_operator",
        "observability",
        "causal_depth",
        "impact",
        "persistence",
        "memory_lineage_stressor",
    ])
    write_csv(gap_csv, gap_slots, [
        "slot_id",
        "bucket",
        "target_domains",
        "source_families",
        "reuse_mode",
        "status",
        "notes",
    ])

    print(json.dumps({
        "inventory_json": str(inventory_json),
        "inventory_csv": str(inventory_csv),
        "gap_slots_csv": str(gap_csv),
        "parsed_cases": summary["parsed_cases"],
        "unique_case_ids": summary["unique_case_ids"],
        "gap_slot_count": summary["gap_slot_count"],
        "errors": len(errors),
    }, ensure_ascii=False, indent=2))
    return 1 if errors or summary["duplicate_case_ids"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
