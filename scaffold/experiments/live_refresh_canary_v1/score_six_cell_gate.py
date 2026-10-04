from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


ARMS = (
    "correct", "corrupted", "live_refresh_correct", "live_refresh",
    "statewise_correct", "statewise_v2_contract_corrected_typedfix",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.run_dir / "manifest.json").read_text(encoding="utf-8"))
    groups = defaultdict(list)
    failures = []
    for state in manifest.get("episodes", {}).values():
        arm = state.get("spec", {}).get("condition")
        if state.get("status") != "SUCCEEDED":
            failures.append({"episode_id": state.get("spec", {}).get("episode_id"), "status": state.get("status")})
            continue
        result = (state.get("attempts") or [{}])[-1].get("result") or {}
        summary = result.get("summary") or {}
        groups[arm].append(summary)

    def metrics(arm):
        rows = groups.get(arm, [])
        n = len(rows)
        objective = sum(bool(r.get("task_success") or r.get("acceptable_safe_terminal")) for r in rows)
        unsafe = sum(bool(r.get("safety_violation")) for r in rows)
        repairs = sum(bool(r.get("repair_performed")) for r in rows)
        calls = sum(len(((r0.get("attempts") or [{}])[-1].get("result") or {}).get("api_metrics") or [])
                    for r0 in manifest.get("episodes", {}).values()
                    if r0.get("spec", {}).get("condition") == arm and r0.get("status") == "SUCCEEDED")
        return {"n": n, "objective": objective, "objective_rate": objective / n if n else None,
                "unsafe": unsafe, "repairs": repairs, "api_calls": calls,
                "api_calls_per_episode": calls / n if n else None}

    table = {arm: metrics(arm) for arm in ARMS}
    expected_n = max((row["n"] for row in table.values()), default=0)
    checks = {
        "engineering_complete": manifest.get("status") == "COMPLETE" and not failures
            and expected_n > 0 and all(row["n"] == expected_n for row in table.values()),
        "vanilla_corruption_gap": table["corrupted"]["objective"] < table["correct"]["objective"],
        "refresh_leaves_gap_or_cost": (
            table["live_refresh"]["objective"] < table["correct"]["objective"]
            or table["live_refresh"]["api_calls_per_episode"]
               > 1.2 * max(table["correct"]["api_calls_per_episode"], 0.001)
        ),
        "statewise_directional_advantage": table["statewise_v2_contract_corrected_typedfix"]["objective"]
            >= table["live_refresh"]["objective"],
        "statewise_activates_on_corruption": table["statewise_v2_contract_corrected_typedfix"]["repairs"] > 0,
        "correct_state_no_unsafe": table["statewise_correct"]["unsafe"] == 0,
        "correct_state_no_repair": table["statewise_correct"]["repairs"] == 0,
        "correct_state_low_regression": table["statewise_correct"]["objective"]
            >= table["correct"]["objective"] - 1,
    }
    engineering = checks["engineering_complete"]
    scientific = all(value for key, value in checks.items() if key != "engineering_complete")
    report = {
        "schema_version": "six-cell-gate-v1", "run_id": manifest.get("run_id"),
        "run_status": manifest.get("status"), "expected_n_per_arm": expected_n,
        "metrics": table, "checks": checks, "engineering_pass": engineering,
        "scientific_signal_pass": scientific, "authorize_scale_up": engineering and scientific,
        "failed_episodes": failures,
        "policy": "A failed scientific check halts scale-up; only evidenced infrastructure/protocol defects may be repaired.",
    }
    (args.run_dir / "six_cell_gate.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["authorize_scale_up"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
