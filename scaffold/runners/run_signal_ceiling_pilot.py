from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path

from scaffold.runners import method_freeze_v1
from scaffold.runners.run_episode_real import _preflight, _write_atomic
from scaffold.statewise import config
from scaffold.statewise.agents import llm_client
from scaffold.statewise.evaluation import failure_taxonomy
from scaffold.statewise.experiments import experimental_conditions, targeted_variants
from scaffold.statewise.runtime import lightweight_runtime


ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "scaffold" / "cases"
DEFAULT_CASES = (
    "case_canary_env_django_py313",
    "case_canary_env_rich_py312",
    "case_canary_fs_django_migrations",
    "case_canary_fs_rich_golden",
    "case_canary_git_black_docs",
    "case_canary_git_rich_release",
)


def totals(calls):
    return {
        "calls": len(calls),
        "total_tokens": sum(int(x.get("total_tokens") or 0) for x in calls),
        "failures": sum(not bool(x.get("ok")) for x in calls),
    }


def arm_summary(arm):
    episode = arm.get("episode", {})
    if not episode:
        runtime = arm.get("runtime_execution", {})
        episode = {
            "status": runtime.get("episode_status"),
            "task_success": runtime.get("oracle", {}).get("task_completed"),
            "acceptable_safe_terminal": runtime.get("oracle", {}).get("acceptable_terminal"),
            "safety_violation": runtime.get("oracle", {}).get("violated"),
            "steps": runtime.get("steps"),
        }
    return {
        "status": episode.get("status"),
        "task_success": bool(episode.get("task_success")),
        "acceptable_safe_terminal": bool(episode.get("acceptable_safe_terminal")),
        "safety_violation": bool(episode.get("safety_violation")),
        "steps": episode.get("steps"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--output-dir", default=str(ROOT / "runs" / "signal_ceiling_pilot"))
    parser.add_argument("--api-profile")
    args = parser.parse_args()
    if config.FAKE_API:
        raise SystemExit("STATECLARIFY_FAKE_API must be false")
    freeze = method_freeze_v1.verify()
    if not freeze["valid"]:
        raise SystemExit("StateWise-v1 freeze mismatch")
    if args.api_profile:
        from scaffold.runners.run_targeted_variant_compare import _select_api_profile
        _select_api_profile(args.api_profile)
    case_ids = tuple(args.case_ids or DEFAULT_CASES)
    started = datetime.now(timezone.utc)
    destination = Path(args.output_dir) / f"signal-ceiling-{started.strftime('%Y%m%dT%H%M%SZ')}.json"
    manifest = {
        "kind": "statewise_signal_ceiling_pilot",
        "complete": False,
        "started_at": started.isoformat(),
        "method_freeze": freeze,
        "case_ids": list(case_ids),
        "trials": args.trials,
        "arms": ["vanilla_corrupted", "statewise_v1", "oracle_statewise"],
        "records": [],
        "measurement_errors": [],
    }
    _write_atomic(destination, manifest)
    preflight = _preflight()
    manifest["preflight"] = preflight
    _write_atomic(destination, manifest)
    if not preflight["ok"]:
        manifest["complete"] = True
        _write_atomic(destination, manifest)
        print(f"manifest={destination.resolve()}")
        return 2

    for trial in range(args.trials):
        for case_id in case_ids:
            print(f"[case:start] {case_id} trial={trial}", flush=True)
            path = CASES / f"{case_id}.json"
            case = json.loads(path.read_text(encoding="utf-8"))
            try:
                with targeted_variants.use_variant("combined"):
                    llm_client.reset_call_metrics()
                    evaluation = lightweight_runtime.run_executable_conditions(str(path))
                    vanilla_calls = llm_client.get_call_metrics()
                    corrupted = evaluation["arms"]["corrupted"]
                    proposal = {
                        "action": corrupted["initial_action"],
                        "rationale": corrupted.get("initial_rationale", ""),
                        "planner_context_memory_ids": corrupted.get("planner_context_memory_ids", []),
                    }
                    llm_client.reset_call_metrics()
                    oracle = lightweight_runtime.run_executable_case(
                        str(path), condition="corrupted",
                        initial_proposal=copy.deepcopy(proposal),
                        support_track="oracle", counterfactual_track="oracle",
                    )
                    oracle_calls = llm_client.get_call_metrics()
                record = {
                    "case_id": case_id,
                    "trial": trial,
                    "vanilla_corrupted": arm_summary(corrupted),
                    "statewise_v1": arm_summary(evaluation["arms"]["mitigated"]),
                    "oracle_statewise": arm_summary(oracle),
                    "api": {"vanilla_and_v1": totals(vanilla_calls), "oracle": totals(oracle_calls)},
                    "raw": {"vanilla_and_v1": evaluation, "oracle": oracle},
                }
                manifest["records"].append(record)
                print(
                    f"[case:done] {case_id} vanilla={record['vanilla_corrupted']['status']} "
                    f"v1={record['statewise_v1']['status']} oracle={record['oracle_statewise']['status']}",
                    flush=True,
                )
            except Exception as exc:
                manifest["measurement_errors"].append({
                    "case_id": case_id, "trial": trial,
                    "error_type": type(exc).__name__, "error": str(exc)[:500],
                })
                print(f"[case:error] {case_id} {type(exc).__name__}", flush=True)
            _write_atomic(destination, manifest)
    manifest["complete"] = not manifest["measurement_errors"]
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    _write_atomic(destination, manifest)
    print(f"manifest={destination.resolve()}")
    return 1 if manifest["measurement_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
