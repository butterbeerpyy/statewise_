from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
ARMS = (
    "statewise_v2_contract_corrected_typedfix",
    "corrupted",
    "rationale_approval",
    "safety_sentry",
)


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--run", required=True, type=Path)
    args = p.parse_args()
    run = args.run.resolve()
    manifest = read(run / "manifest.json")
    summary = read(run / "pilot_summary.json")
    snapshot = read(PACKAGE / "snapshot.json")
    matrix = read(PACKAGE / "paired_matrix.json")
    errors = []

    def require(ok: bool, msg: str) -> None:
        if not ok:
            errors.append(msg)

    states = list(manifest.get("episodes", {}).values())
    expected = {entry["case_id"]: entry for entry in snapshot["cases"]}
    by_case: dict[str, list] = {}
    for state in states:
        by_case.setdefault(state["spec"]["case_id"], []).append(state)
    require(manifest.get("status") == "COMPLETE", "manifest is not COMPLETE")
    require(len(states) == 160, "episode count is not 160")
    require(set(by_case) == set(expected), "case IDs differ from frozen 40-case snapshot")
    require(all(len(rows) == 4 for rows in by_case.values()), "not exactly four arms per case")
    require(all(tuple(row["spec"]["condition"] for row in rows) == ARMS for rows in by_case.values()), "arm order/identity drift")
    require(all(state.get("status") == "SUCCEEDED" for state in states), "final episode status is not SUCCEEDED")
    require(all(state["spec"].get("trial") == 0 for state in states), "foreign trial present")
    require(all(state["spec"].get("payload", {}).get("case_sha256") == expected[state["spec"]["case_id"]]["sha256"] for state in states), "case hash drift")
    require(summary.get("pairing_valid") is True, "managed pairing summary is invalid")
    require(len(matrix.get("cells", [])) == 160, "frozen paired matrix is not 160 cells")

    config = manifest.get("experiment_config", {})
    manager = manifest.get("manager", {})
    require(config.get("model") == "gpt-5.6-sol", "model drift")
    require(config.get("temperature") == 0.0, "temperature drift")
    require(config.get("arms") == list(ARMS), "configuration arm drift")
    require(config.get("worker_isolation") == "process", "process isolation drift")
    require(config.get("provider_profiles") == ["api_02"], "provider drift")
    require(manager.get("retry_policy", {}).get("max_attempts") == 3, "retry budget drift")

    repeated = [state for state in states if len(state.get("attempts", [])) > 1]
    require(len(repeated) == 3, "unexpected repeated-episode count")
    recovery_kinds = Counter()
    for state in repeated:
        for attempt in state.get("attempts", [])[:-1]:
            recovery_kinds[(attempt.get("failure") or {}).get("kind")] += 1
        require(state.get("attempts", [])[-1].get("status") == "SUCCEEDED", "repeated episode did not end successfully")
    require(set(recovery_kinds) == {"model.response_contract"}, "non-contract recovery failure present")

    report = {
        "schema_version": "paper-external40-closure-audit-v1",
        "valid": not errors,
        "errors": errors,
        "run_id": manifest.get("run_id"),
        "manifest_status": manifest.get("status"),
        "logical_episodes": len(states),
        "final_status_counts": dict(Counter(state.get("status") for state in states)),
        "arm_counts": dict(Counter(state["spec"]["condition"] for state in states)),
        "case_count": len(by_case),
        "attempt_count": sum(len(state.get("attempts", [])) for state in states),
        "repeated_episode_count": len(repeated),
        "recovery_failure_kinds": dict(recovery_kinds),
        "snapshot_sha256": sha(PACKAGE / "snapshot.json"),
        "statistics_contract": "use only each episode's final successful attempt",
    }
    output = run / "external40_closure_audit.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
