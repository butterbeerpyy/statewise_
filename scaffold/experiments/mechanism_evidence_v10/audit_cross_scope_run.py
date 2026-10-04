from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent / "frozen"
FULL = "statewise_v2_contract_corrected_typedfix"
RQ4 = Path('runs/formal_v10_rq4_ablations150_gpt56sol_20260822_r1')


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    run = args.run.resolve()
    manifest = read(run / "manifest.json")
    summary = read(run / "pilot_summary.json")
    snapshot_path = PACKAGE / "cross_scope_same_key_v10" / "snapshot.json"
    snapshot = read(snapshot_path)
    plan = read(PACKAGE / "cross_scope_plan.json")
    freeze = read(PACKAGE / "statewise_typedfix_cross_scope_freeze.json")
    rq4 = read(RQ4 / "manifest.json")

    errors: list[str] = []
    episodes = manifest.get("episodes", {})
    states = list(episodes.values())
    entries = snapshot.get("cases", [])
    expected_cases = {entry["case_id"] for entry in entries}
    actual_cases = {state["spec"]["case_id"] for state in states}
    rq4_full_cases = {
        state["spec"]["case_id"]
        for state in rq4.get("episodes", {}).values()
        if state["spec"].get("condition") == FULL
    }

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(manifest.get("status") == "COMPLETE", "manifest is not COMPLETE")
    require(len(episodes) == 150, "manifest does not contain 150 episodes")
    require(len(actual_cases) == 150, "case IDs are not unique and complete")
    require(actual_cases == expected_cases, "manifest case IDs differ from frozen snapshot")
    require(actual_cases == rq4_full_cases, "RQ4 Full pairing is incomplete")
    require(all(state.get("status") == "SUCCEEDED" for state in states), "not all final states succeeded")
    require(all(state["spec"].get("condition") == FULL for state in states), "foreign arm present")
    require(all(state["spec"].get("trial") == 0 for state in states), "foreign trial present")
    require(sha256(snapshot_path) == freeze["dataset"]["snapshot_sha256"], "snapshot/freeze hash drift")
    require(sha256(snapshot_path) == plan["overlay_dataset"]["snapshot_sha256"], "snapshot/plan hash drift")
    by_case = {entry["case_id"]: entry for entry in entries}
    require(all(
        state["spec"]["payload"].get("case_sha256") == by_case[state["spec"]["case_id"]]["sha256"]
        for state in states
    ), "episode case hash differs from frozen snapshot")

    config = manifest.get("experiment_config", {})
    manager = manifest.get("manager", {})
    require(config.get("model") == "gpt-5.6-sol", "model drift")
    require(config.get("temperature") == 0.0, "temperature drift")
    require(config.get("arms") == [FULL], "arm configuration drift")
    require(config.get("provider_profiles") == ["api_02"], "provider drift")
    require(config.get("worker_isolation") == "process", "process isolation drift")
    require(manager.get("retry_policy", {}).get("max_attempts") == 3, "retry budget drift")
    require(summary.get("pairing_valid") is True, "managed-run pairing summary failed")
    require(rq4.get("status") == "COMPLETE", "paired RQ4 source is not COMPLETE")

    attempts = [attempt for state in states for attempt in state.get("attempts", [])]
    repeated = [state for state in states if len(state.get("attempts", [])) > 1]
    foreign_profiles = sorted({
        attempt.get("provider_profile") for attempt in attempts
        if attempt.get("provider_profile") != "api_02"
    })
    require(not foreign_profiles, "foreign provider profile present")
    require(len(repeated) == 1, "unexpected repeated-episode count")
    if repeated:
        history = repeated[0].get("attempts", [])
        require(
            (history[0].get("failure") or {}).get("kind") == "model.response_contract"
            and history[-1].get("status") == "SUCCEEDED",
            "recovery history differs from recorded response-contract retry",
        )

    report = {
        "schema_version": "cross-scope-closure-audit-v1",
        "valid": not errors,
        "errors": errors,
        "run_id": manifest.get("run_id"),
        "manifest_status": manifest.get("status"),
        "config_fingerprint": manifest.get("config_fingerprint"),
        "snapshot_sha256": sha256(snapshot_path),
        "logical_episodes": len(states),
        "final_status_counts": dict(Counter(state.get("status") for state in states)),
        "attempt_count": len(attempts),
        "repeated_episode_count": len(repeated),
        "recovery_failure_kinds": dict(Counter(
            (attempt.get("failure") or {}).get("kind")
            for state in repeated for attempt in state.get("attempts", [])[:-1]
        )),
        "rq4_full_pair_count": len(actual_cases & rq4_full_cases),
        "case_hashes_valid": "episode case hash differs from frozen snapshot" not in errors,
        "foreign_provider_profiles": foreign_profiles,
        "statistics_contract": "use only each episode's final successful attempt",
    }
    output = run / "cross_scope_closure_audit.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
