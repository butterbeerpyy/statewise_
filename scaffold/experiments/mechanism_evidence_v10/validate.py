from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from build import (
    ARMS,
    FULL,
    OUTPUT_ROOT,
    RQ4_RUN,
    SOURCE_METHOD_FREEZE,
    SOURCE_ROOT,
    SOURCE_SNAPSHOT_SHA256,
    canonical_sha256,
    load_source,
    read_json,
    sha256,
)


EXPECTED_ARM_FINGERPRINTS = {
    FULL: "sha256:0804b97693cb2f4cab236f325347b3c227c391572aa7e3048f85657640cc899e",
    "statewise_ablation_no_replan": "sha256:f9cd455bf0d540010cb971a5c0dd4127273ecd96e2c8540842109c20c29fc3c3",
    "statewise_ablation_no_residual_gate": "sha256:46573f2444990bc033149db413fec2952d2d1be0e9c8f5744024d141db197186",
}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def validate_overlay(
    output_root: Path,
    source_cases: list[dict[str, Any]],
    errors: list[str],
) -> None:
    plan = read_json(output_root / "cross_scope_plan.json")
    snapshot_path = output_root / "cross_scope_same_key_v10" / "snapshot.json"
    snapshot = read_json(snapshot_path)
    cases_root = snapshot_path.parent / "cases"
    if plan.get("case_count") != 150 or snapshot.get("case_count") != 150:
        fail(errors, "cross-scope package must contain 150 cases")
    if plan.get("new_api_episode_count") != 150:
        fail(errors, "cross-scope plan must request exactly 150 new episodes")
    by_id = {case["case_id"]: case for case in source_cases}
    entries = {entry["case_id"]: entry for entry in snapshot["cases"]}
    if set(by_id) != set(entries):
        fail(errors, "cross-scope source and overlay case IDs differ")
        return
    allowed_top_level = {"context_memories", "mechanism_evidence_overlay"}
    for case_id, source in by_id.items():
        entry = entries[case_id]
        path = cases_root / entry["file"]
        if sha256(path) != entry["sha256"]:
            fail(errors, f"cross-scope case hash mismatch: {case_id}")
            continue
        overlay = read_json(path)
        changed = {
            key
            for key in set(source) | set(overlay)
            if canonical_sha256(source.get(key)) != canonical_sha256(overlay.get(key))
        }
        if changed != allowed_top_level:
            fail(errors, f"unexpected cross-scope fields for {case_id}: {sorted(changed)}")
            continue
        source_context = list(source.get("context_memories") or [])
        overlay_context = list(overlay.get("context_memories") or [])
        if overlay_context[:-1] != source_context or len(overlay_context) != len(source_context) + 1:
            fail(errors, f"cross-scope context delta is not one append: {case_id}")
            continue
        decoy = overlay_context[-1]
        current_scope = source.get("environment", {}).get("scope", {})
        if decoy.get("key") != source.get("memory_key"):
            fail(errors, f"cross-scope decoy key mismatch: {case_id}")
        if decoy.get("scope", {}).get("repository") == current_scope.get("repository"):
            fail(errors, f"cross-scope repository does not differ: {case_id}")

    recorded = plan.get("overlay_dataset", {}).get("snapshot_sha256")
    if recorded != sha256(snapshot_path):
        fail(errors, "cross-scope plan snapshot hash mismatch")
    freeze = read_json(output_root / "statewise_typedfix_cross_scope_freeze.json")
    source_freeze = read_json(SOURCE_METHOD_FREEZE)
    if freeze.get("fingerprint") != source_freeze.get("fingerprint"):
        fail(errors, "cross-scope freeze changed the method fingerprint")
    if freeze.get("files") != source_freeze.get("files"):
        fail(errors, "cross-scope freeze changed the method source hashes")
    if freeze.get("dataset", {}).get("snapshot_sha256") != sha256(snapshot_path):
        fail(errors, "cross-scope freeze dataset hash mismatch")


def validate_plan(output_root: Path, name: str, expected_cases: int, errors: list[str]) -> dict:
    plan = read_json(output_root / f"{name}_targeted_plan.json")
    if plan.get("case_count") != expected_cases:
        fail(errors, f"{name} case count differs from {expected_cases}")
    if tuple(plan.get("arms") or ()) != ARMS[name]:
        fail(errors, f"{name} arm list differs from the frozen contrast")
    if plan.get("logical_episode_count") != expected_cases * 2:
        fail(errors, f"{name} logical cell count is incorrect")
    if plan.get("new_api_episode_count") != 0:
        fail(errors, f"{name} must reuse RQ4 cells instead of rerunning")
    fingerprint = "sha256:" + canonical_sha256(
        {
            "source": plan["source_dataset"],
            "arms": plan["arms"],
            "cases": plan["cases"],
        }
    )
    if plan.get("selection_fingerprint") != fingerprint:
        fail(errors, f"{name} selection fingerprint mismatch")
    return plan


def validate_rq4(
    manifest_path: Path,
    plans: list[dict[str, Any]],
    errors: list[str],
) -> dict[str, Any]:
    if not manifest_path.is_file():
        fail(errors, f"RQ4 manifest missing: {manifest_path}")
        return {"status": "MISSING"}
    manifest = read_json(manifest_path)
    config = manifest.get("experiment_config", {})
    dataset = manifest.get("dataset", {})
    manager = manifest.get("manager", {})
    expected = {
        "model": "gpt-5.6-sol",
        "temperature": 0.0,
        "api_profile": "api_02",
        "json_response_format": False,
        "runtime_concurrency": 10,
        "worker_isolation": "process",
        "trials": 1,
    }
    for key, value in expected.items():
        if config.get(key) != value:
            fail(errors, f"RQ4 config mismatch for {key}: {config.get(key)!r}")
    if dataset.get("snapshot_sha256") != SOURCE_SNAPSHOT_SHA256:
        fail(errors, "RQ4 dataset hash differs from final v10")
    if manager.get("retry_policy", {}).get("max_attempts") != 3:
        fail(errors, "RQ4 max_attempts differs from 3")
    registry = config.get("arm_registry", {})
    for arm, expected_fingerprint in EXPECTED_ARM_FINGERPRINTS.items():
        implementation = registry.get(arm, {}).get("implementation", {})
        if implementation.get("fingerprint") != expected_fingerprint:
            fail(errors, f"RQ4 arm fingerprint mismatch: {arm}")
        if arm != FULL and implementation.get("base_fingerprint") != EXPECTED_ARM_FINGERPRINTS[FULL]:
            fail(errors, f"RQ4 ablation base fingerprint mismatch: {arm}")
    episodes = manifest.get("episodes", {})
    for plan in plans:
        for row in plan["cases"]:
            for arm in plan["arms"]:
                episode_id = f"{row['case_id']}--{arm}--trial-000"
                episode = episodes.get(episode_id)
                if episode is None:
                    fail(errors, f"RQ4 exact cell missing: {episode_id}")
                    continue
                spec = episode.get("spec", {})
                if (
                    spec.get("case_id") != row["case_id"]
                    or spec.get("condition") != arm
                    or spec.get("trial") != 0
                ):
                    fail(errors, f"RQ4 exact cell spec mismatch: {episode_id}")
    return {
        "run_id": manifest.get("run_id"),
        "status": manifest.get("status"),
        "config_fingerprint": manifest.get("config_fingerprint"),
        "episode_count": len(episodes),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--rq4-manifest", type=Path, default=RQ4_RUN / "manifest.json")
    args = parser.parse_args()
    errors: list[str] = []
    source_snapshot, source_cases = load_source(args.source_root.resolve())
    if source_snapshot.get("snapshot_id") != "w1_contract_corrected_v10_permission_enabled_sensitivity":
        fail(errors, "source snapshot id differs from final v10")
    output_root = args.output_root.resolve()
    validate_overlay(output_root, source_cases, errors)
    replanning = validate_plan(output_root, "replanning", 25, errors)
    residual = validate_plan(output_root, "residual_gate", 20, errors)
    rq4 = validate_rq4(args.rq4_manifest.resolve(), [replanning, residual], errors)
    report = {
        "valid": not errors,
        "errors": errors,
        "source_snapshot_sha256": SOURCE_SNAPSHOT_SHA256,
        "cross_scope_snapshot_sha256": sha256(
            output_root / "cross_scope_same_key_v10" / "snapshot.json"
        ),
        "replanning_selection_fingerprint": replanning.get("selection_fingerprint"),
        "residual_gate_selection_fingerprint": residual.get("selection_fingerprint"),
        "rq4": rq4,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
