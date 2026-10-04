from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SNAPSHOT_ID = "w1_contract_corrected_v10_permission_enabled_sensitivity"
EXPECTED_PARENT_SHA256 = (
    "25f08c7ec7f5cee5855dcddbfc9e538bab79a509aa8580dbd7501ef396c2af34"
)
EXPECTED_COHORT_SIZE = 20
EXPECTED_CHANGED_CASES = 18


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _is_semantic_should_act(case: dict[str, Any]) -> bool:
    expected = case.get("expected", {}).get("correct", {}).get("episode", {})
    completion = case.get("execution", {}).get("oracle", {}).get(
        "completion_actions", []
    )
    return (
        case.get("domain") == "user_private_semantics"
        and expected.get("task_success") is True
        and bool(completion)
    )


def _allow_rule(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": copy.deepcopy(action),
        "decision": "ALLOW",
        "reason": "permission_enabled_sensitivity_exact_completion_action",
    }


def materialize(source: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    snapshot_path = source / "snapshot.json"
    parent_sha = _sha256(snapshot_path)
    if parent_sha != EXPECTED_PARENT_SHA256:
        raise RuntimeError(
            f"formal-v9 parent SHA mismatch: expected {EXPECTED_PARENT_SHA256}, "
            f"got {parent_sha}"
        )
    parent = json.loads(snapshot_path.read_text(encoding="utf-8"))
    output_cases = output / "cases"
    output_cases.mkdir(parents=True)

    entries: list[dict[str, Any]] = []
    cohort: list[str] = []
    changed: dict[str, list[str]] = {}
    for entry in parent["cases"]:
        source_case = source / "cases" / entry["file"]
        case = json.loads(source_case.read_text(encoding="utf-8"))
        changes: list[str] = []
        if _is_semantic_should_act(case):
            cohort.append(case["case_id"])
            if not case.get("permission_policy"):
                completion = case["execution"]["oracle"]["completion_actions"]
                case["permission_policy"] = {
                    "default": "DENY",
                    "rules": [_allow_rule(action) for action in completion],
                }
                changes.append("add_exact_completion_permission_policy")
                changed[case["case_id"]] = changes

        overlay = case.setdefault("benchmark_overlay", {})
        overlay["overlay_id"] = SNAPSHOT_ID
        overlay["parent_overlay_id"] = parent["snapshot_id"]
        overlay["changes"] = list(overlay.get("changes", [])) + changes

        target = output_cases / entry["file"]
        _write_json(target, case)
        updated = copy.deepcopy(entry)
        updated["source_sha256"] = entry["sha256"]
        updated["sha256"] = _sha256(target)
        updated["overlay_changes"] = changes
        entries.append(updated)

    if len(cohort) != EXPECTED_COHORT_SIZE:
        raise RuntimeError(
            f"semantic SHOULD_ACT cohort drift: {len(cohort)} != {EXPECTED_COHORT_SIZE}"
        )
    if len(changed) != EXPECTED_CHANGED_CASES:
        raise RuntimeError(
            f"permission overlay drift: {len(changed)} != {EXPECTED_CHANGED_CASES}"
        )

    snapshot = {
        "schema_version": parent["schema_version"],
        "snapshot_id": SNAPSHOT_ID,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "purpose": (
            "Permission-enabled construct-validity sensitivity over the formal-v9 "
            "semantic SHOULD_ACT cohort"
        ),
        "reporting_status": "sensitivity_only_not_primary_heldout",
        "parent_snapshot": {
            "snapshot_id": parent["snapshot_id"],
            "sha256": parent_sha,
        },
        "selection_rule": (
            "domain=user_private_semantics AND expected.correct.episode.task_success=true "
            "AND execution.oracle.completion_actions is non-empty"
        ),
        "case_count": len(entries),
        "sensitivity_cohort_case_ids": sorted(cohort),
        "changed_cases": changed,
        "permission_contract": {
            "default": "DENY",
            "allow_source": "execution.oracle.completion_actions",
            "method_code_changed": False,
            "primary_scores_changed": False,
        },
        "cases": entries,
    }
    _write_json(output / "snapshot.json", snapshot)
    return snapshot


def validate(source: Path, output: Path) -> dict[str, Any]:
    parent = json.loads((source / "snapshot.json").read_text(encoding="utf-8"))
    snapshot_path = output / "snapshot.json"
    overlay = json.loads(snapshot_path.read_text(encoding="utf-8"))
    parent_entries = {entry["case_id"]: entry for entry in parent["cases"]}
    changed = []
    errors = []
    for entry in overlay["cases"]:
        case_id = entry["case_id"]
        parent_entry = parent_entries[case_id]
        parent_case = json.loads(
            (source / "cases" / parent_entry["file"]).read_text(encoding="utf-8")
        )
        case_path = output / "cases" / entry["file"]
        case = json.loads(case_path.read_text(encoding="utf-8"))
        if _sha256(case_path) != entry["sha256"]:
            errors.append(f"{case_id}: case SHA mismatch")
        if entry.get("overlay_changes"):
            changed.append(case_id)
            completion = case["execution"]["oracle"]["completion_actions"]
            policy = case.get("permission_policy", {})
            actions = [rule.get("action") for rule in policy.get("rules", [])]
            if policy.get("default") != "DENY":
                errors.append(f"{case_id}: permission default is not DENY")
            if actions != completion:
                errors.append(f"{case_id}: ALLOW rules differ from completion actions")
            if any(rule.get("decision") != "ALLOW" for rule in policy.get("rules", [])):
                errors.append(f"{case_id}: non-ALLOW rule in exact allow list")
        else:
            expected = copy.deepcopy(parent_case)
            expected_overlay = expected.setdefault("benchmark_overlay", {})
            expected_overlay["overlay_id"] = SNAPSHOT_ID
            expected_overlay["parent_overlay_id"] = parent["snapshot_id"]
            expected_overlay["changes"] = list(expected_overlay.get("changes", []))
            if case != expected:
                errors.append(f"{case_id}: non-target case changed beyond overlay provenance")

    report = {
        "schema_version": "permission-enabled-sensitivity-validation-v1",
        "status": "VALID" if not errors else "INVALID",
        "snapshot_id": overlay["snapshot_id"],
        "snapshot_sha256": _sha256(snapshot_path),
        "parent_snapshot_sha256": _sha256(source / "snapshot.json"),
        "case_count": len(overlay["cases"]),
        "sensitivity_cohort_count": len(overlay["sensitivity_cohort_case_ids"]),
        "changed_case_count": len(changed),
        "changed_case_ids": sorted(changed),
        "checks": {
            "parent_sha_matches": _sha256(source / "snapshot.json")
            == EXPECTED_PARENT_SHA256,
            "exactly_18_cases_changed": len(changed) == EXPECTED_CHANGED_CASES,
            "cohort_has_20_cases": len(overlay["sensitivity_cohort_case_ids"])
            == EXPECTED_COHORT_SIZE,
            "rules_copy_existing_completion_actions_exactly": not any(
                "ALLOW rules differ" in error for error in errors
            ),
            "all_policies_fail_closed": not any(
                "default is not DENY" in error for error in errors
            ),
            "non_target_payloads_unchanged": not any(
                "non-target case changed" in error for error in errors
            ),
        },
        "errors": errors,
    }
    _write_json(output / "VALIDATION.json", report)
    if errors or not all(report["checks"].values()):
        raise RuntimeError(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    materialize(source, output)
    report = validate(source, output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
