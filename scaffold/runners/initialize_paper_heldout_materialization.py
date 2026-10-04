from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "dataset_design" / "artifacts" / "paper_benchmark_v1"
SLOTS_PATH = SOURCE_DIR / "paper_heldout_300_slots_v1.json"
SPEC_PATH = SOURCE_DIR / "paper_heldout_300_spec_v1.json"
OUTPUT_DIR = (
    ROOT / "dataset_design" / "artifacts" / "paper_heldout_materialization_v1"
)
SELECTION_SEED = "swe-statebench-paper-heldout-selection-v1"

EXCLUSION_MANIFESTS = (
    ROOT / "scaffold" / "experiments" / "statewise_current_pool_v1.json",
    ROOT / "scaffold" / "experiments" / "paper_dev_stress_96_v1.json",
    ROOT / "scaffold" / "experiments" / "paper_failure_regression_40_v1.json",
    ROOT / "dataset_design" / "artifacts" / "statewise_300_case_final_manifest.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _case_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        case_id = value.get("case_id")
        if isinstance(case_id, str) and case_id:
            found.add(case_id)
        for item in value.values():
            found.update(_case_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_case_ids(item))
    return found


def _selection_rank(slot_id: str) -> str:
    return hashlib.sha256(f"{SELECTION_SEED}|{slot_id}".encode("utf-8")).hexdigest()


def _annotation_row(slot: dict[str, Any], role: str) -> dict[str, Any]:
    return {
        "slot_id": slot["slot_id"],
        "selection_role": role,
        "case_id": None,
        "case_sha256": None,
        "annotator_id": None,
        "annotation_status": "NOT_STARTED",
        "state_truth": None,
        "state_scope": None,
        "corruption_valid": None,
        "expected_behavior": None,
        "action_contract": None,
        "oracle_support_states": None,
        "safety_invariant": None,
        "task_terminal_contract": None,
        "canonical_safe_policy_reaches_terminal": None,
        "fixture_reset_verified": None,
        "notes": None,
    }


def main() -> int:
    slots_document = json.loads(SLOTS_PATH.read_text(encoding="utf-8"))
    slots = list(slots_document["slots"])
    if len(slots) != 300:
        raise ValueError(f"expected 300 slots, found {len(slots)}")

    by_domain: dict[str, list[dict[str, Any]]] = {}
    for slot in slots:
        by_domain.setdefault(slot["operational_domain"], []).append(slot)
    if sorted(len(items) for items in by_domain.values()) != [60] * 5:
        raise ValueError("expected five domains with 60 slots each")

    roles: dict[str, str] = {}
    for domain, items in sorted(by_domain.items()):
        ranked = sorted(items, key=lambda item: _selection_rank(item["slot_id"]))
        for slot in ranked[:2]:
            roles[slot["slot_id"]] = "infrastructure_canary"
        for slot in ranked[2:42]:
            roles[slot["slot_id"]] = "headline"
        for slot in ranked[42:]:
            roles[slot["slot_id"]] = "reserve"

    registry = []
    for slot in sorted(slots, key=lambda item: item["slot_id"]):
        role = roles[slot["slot_id"]]
        registry.append(
            {
                **slot,
                "selection_role": role,
                "selection_rank": _selection_rank(slot["slot_id"]),
                "materialization_status": "UNMATERIALIZED",
                "blueprint_sha256": None,
                "fixture_sha256": None,
                "oracle_sha256": None,
                "schema_valid": False,
                "deterministic_closure_valid": False,
                "leakage_audit_status": "NOT_RUN",
                "annotation_a_status": "NOT_STARTED",
                "annotation_b_status": "NOT_STARTED",
                "adjudication_status": "NOT_STARTED",
            }
        )

    exclusions: dict[str, list[str]] = {}
    exclusion_sources = []
    for path in EXCLUSION_MANIFESTS:
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        ids = sorted(_case_ids(payload))
        exclusion_sources.append(
            {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": _sha256(path),
                "case_count": len(ids),
            }
        )
        for case_id in ids:
            exclusions.setdefault(case_id, []).append(
                str(path.relative_to(ROOT)).replace("\\", "/")
            )

    selection = {
        "schema_version": "swe-statebench-heldout-selection-v1",
        "benchmark_id": "swe_statebench_paper_heldout_300_v1",
        "status": "SELECTION_FROZEN_CASES_UNMATERIALIZED",
        "selection_seed": SELECTION_SEED,
        "selection_algorithm": (
            "within each 60-slot domain, sort by sha256(seed + '|' + slot_id); "
            "first 2 are infrastructure canaries, next 40 are headline, final "
            "18 are reserve"
        ),
        "source_slots": {
            "path": str(SLOTS_PATH.relative_to(ROOT)).replace("\\", "/"),
            "sha256": _sha256(SLOTS_PATH),
        },
        "source_spec": {
            "path": str(SPEC_PATH.relative_to(ROOT)).replace("\\", "/"),
            "sha256": _sha256(SPEC_PATH),
        },
        "counts": {
            "total": 300,
            "infrastructure_canary": 10,
            "headline": 200,
            "reserve": 90,
        },
        "domain_counts": {
            domain: {
                role: sum(
                    1
                    for slot in items
                    if roles[slot["slot_id"]] == role
                )
                for role in ("infrastructure_canary", "headline", "reserve")
            }
            for domain, items in sorted(by_domain.items())
        },
        "rules": [
            "canary trajectories are excluded from headline statistics",
            "headline slots cannot be exchanged with reserves after outcomes are observed",
            "all development and diagnostic case IDs are excluded",
            "annotator B must not receive annotator A records",
            "adjudication begins only after both annotation packages are sealed",
        ],
    }

    annotation_slots = [
        slot for slot in slots if roles[slot["slot_id"]] == "headline"
    ]
    annotation_slots.sort(key=lambda item: item["slot_id"])
    annotation_a = [_annotation_row(slot, "headline") for slot in annotation_slots]
    annotation_b = [_annotation_row(slot, "headline") for slot in annotation_slots]
    adjudication = [
        {
            "slot_id": slot["slot_id"],
            "case_id": None,
            "annotation_a_sha256": None,
            "annotation_b_sha256": None,
            "disagreement_fields": [],
            "adjudication_status": "NOT_STARTED",
            "adjudicated_record": None,
            "adjudicator_id": None,
            "notes": None,
        }
        for slot in annotation_slots
    ]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_DIR / "selection_manifest.json", selection)
    _write_json(OUTPUT_DIR / "materialization_registry.json", {
        "schema_version": "swe-statebench-materialization-registry-v1",
        "selection_manifest_sha256": None,
        "cases": registry,
    })
    _write_csv(OUTPUT_DIR / "materialization_registry.csv", registry)
    _write_json(OUTPUT_DIR / "development_exclusions.json", {
        "schema_version": "swe-statebench-development-exclusions-v1",
        "sources": exclusion_sources,
        "excluded_case_count": len(exclusions),
        "excluded_cases": [
            {"case_id": case_id, "sources": sources}
            for case_id, sources in sorted(exclusions.items())
        ],
    })
    _write_jsonl(OUTPUT_DIR / "annotations" / "annotator_a" / "records.jsonl", annotation_a)
    _write_jsonl(OUTPUT_DIR / "annotations" / "annotator_b" / "records.jsonl", annotation_b)
    _write_jsonl(OUTPUT_DIR / "annotations" / "adjudication" / "records.jsonl", adjudication)

    selection_hash = _sha256(OUTPUT_DIR / "selection_manifest.json")
    registry_path = OUTPUT_DIR / "materialization_registry.json"
    registry_document = json.loads(registry_path.read_text(encoding="utf-8"))
    registry_document["selection_manifest_sha256"] = selection_hash
    _write_json(registry_path, registry_document)

    readme = f"""# SWE-StateBench paper held-out materialization v1

Status: `SELECTION_FROZEN_CASES_UNMATERIALIZED`

- Source slots: `{SLOTS_PATH.relative_to(ROOT).as_posix()}`
- Selection seed: `{SELECTION_SEED}`
- Infrastructure canaries: 10 (2/domain; excluded from headline)
- Headline cases: 200 (40/domain)
- Reserve cases: 90 (18/domain)
- Development case IDs excluded: {len(exclusions)}

## Required order

1. Materialize case + fixture + deterministic oracle for the frozen slot.
2. Pass schema, reset, canonical safe-policy closure, and leakage checks.
3. Seal the case hash.
4. Give the sealed evidence package independently to annotator A and B.
5. Do not expose either annotator's answers to the other.
6. Seal both annotation files, then adjudicate disagreements.
7. Run the 10 infrastructure canaries. Their trajectories never enter headline results.
8. Freeze the 200 headline cases before any method outcome is inspected.

The blank annotation files are intentionally identical templates. Independence
comes from access control and workflow, not from generating two labels with the
same annotator.
"""
    (OUTPUT_DIR / "README.md").write_text(readme, encoding="utf-8", newline="\n")

    print(json.dumps({
        "output": str(OUTPUT_DIR),
        "selection_sha256": selection_hash,
        "headline": 200,
        "canary": 10,
        "reserve": 90,
        "excluded_case_ids": len(exclusions),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
