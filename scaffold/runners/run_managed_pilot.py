from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any, Mapping

from scaffold.runners import method_freeze_v1
from scaffold.runners.run_episode_real import _preflight
from scaffold.runners.run_targeted_variant_compare import _select_api_profile
from scaffold.statewise import config
from scaffold.statewise.agents import llm_client
from scaffold.statewise.core import action_model
from scaffold.statewise.experiments import pilot_conditions
from scaffold.statewise.experiments.experiment_manager import (
    EpisodeSpec,
    ExperimentFailure,
    ExperimentManager,
    FailureKind,
    RetryPolicy,
    canonical_fingerprint,
    verify_dataset_snapshot,
    write_atomic,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT = ROOT / "scaffold" / "experiments" / "test_set_42_v1.json"
CASES_ROOT = ROOT / "scaffold" / "cases"
DEFAULT_OUTPUT_ROOT = ROOT / "runs" / "managed_pilot"
MEASUREMENT_CODE_FILES = (
    "scaffold/runners/run_managed_pilot.py",
    "scaffold/statewise/experiments/pilot_conditions.py",
    "scaffold/statewise/experiments/experimental_conditions.py",
    "scaffold/statewise/experiments/attribution_v2.py",
    "scaffold/statewise/experiments/baseline_interactions.py",
    "scaffold/statewise/experiments/safety_sentry_baseline.py",
    "scaffold/statewise/experiments/memlineage_baseline.py",
    "scaffold/statewise/experiments/live_refresh_baseline.py",
    "scaffold/statewise/experiments/critic_tool_grounded_baseline.py",
    "scaffold/statewise/experiments/experiment_manager.py",
    "scaffold/statewise/runtime/lightweight_runtime.py",
)


def _measurement_code_fingerprints():
    return {
        relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        for relative in MEASUREMENT_CODE_FILES
    }


def _verify_method_freeze():
    freeze = method_freeze_v1.verify()
    if not freeze["valid"]:
        raise SystemExit("StateWise-v1 freeze mismatch")
    return freeze


def _configure_api_profile(name):
    if name and name != "fake":
        _select_api_profile(name)
        config.FAKE_API = False
        return name
    if name == "fake":
        config.FAKE_API = True
        return "fake"
    return None


def _ordered_profiles(primary, fallbacks=()):
    return tuple(dict.fromkeys(
        profile for profile in (primary, *(fallbacks or ())) if profile
    ))


def _preflight_profiles(profiles):

    attempts = []
    profiles = _ordered_profiles(None, profiles)
    for profile in profiles:
        _configure_api_profile(profile)
        result = _preflight()
        attempts.append({"profile": profile, **result})
        if result.get("ok"):
            provider_order = (profile,) + tuple(
                candidate for candidate in profiles if candidate != profile
            )
            return {
                "ok": True,
                "selected_profile": profile,
                "attempts": attempts,
            }, provider_order
    return {
        "ok": False,
        "selected_profile": None,
        "attempts": attempts,
    }, profiles


def _api_totals(metrics):
    metrics = [item for item in (metrics or []) if isinstance(item, Mapping)]
    return {
        "calls": len(metrics),
        "failed_calls": sum(item.get("ok") is False for item in metrics),
        "prompt_tokens": sum(int(item.get("prompt_tokens") or 0) for item in metrics),
        "completion_tokens": sum(int(item.get("completion_tokens") or 0) for item in metrics),
        "total_tokens": sum(int(item.get("total_tokens") or 0) for item in metrics),
        "latency_seconds": round(sum(float(
            item.get("elapsed_seconds", item.get("latency_seconds", 0)) or 0
        ) for item in metrics), 4),
    }


def _failure_kind_from_metric(metric: Mapping[str, Any]) -> FailureKind:
    name = str(metric.get("error_type", "")).lower()
    if "authentication" in name or "permissiondenied" in name:
        return FailureKind.API_AUTH
    if "ratelimit" in name:
        return FailureKind.API_RATE_LIMIT
    if "timeout" in name:
        return FailureKind.API_TIMEOUT
    if "connection" in name:
        return FailureKind.API_CONNECTION
    if "internalserver" in name or "serviceunavailable" in name:
        return FailureKind.API_SERVER
    if "badrequest" in name or "unprocessable" in name:
        return FailureKind.API_REQUEST
    return FailureKind.UNKNOWN


def _raise_for_failed_metrics(metrics, *, partial=None):
    failures = [item for item in metrics if isinstance(item, Mapping) and item.get("ok") is False]
    if not failures:
        return
    last = failures[-1]
    raise ExperimentFailure(
        _failure_kind_from_metric(last),
        f"episode contained failed API call: {last.get('error_type', 'unknown')}",
        details={
            "api_metrics": metrics,
            "partial_summary": partial,
        },
    )


def _load_snapshot_entries(snapshot_path: Path, wanted_cases, arms, trials):
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    selected = []
    excluded = []
    wanted = set(wanted_cases or [])
    for entry in snapshot["cases"]:
        if wanted and entry["case_id"] not in wanted:
            continue
        case_path = CASES_ROOT / entry["file"]
        case = json.loads(case_path.read_text(encoding="utf-8"))
        if case.get("execution", {}).get("tier") != "lightweight":
            excluded.append({
                "case_id": entry["case_id"],
                "file": entry["file"],
                "reason": "execution.tier is not lightweight",
            })
            continue
        selected.append(entry)
    unknown = wanted - {entry["case_id"] for entry in snapshot["cases"]}
    if unknown:
        raise ValueError(f"case ids are absent from snapshot: {sorted(unknown)}")
    episodes = []
    for trial in range(trials):
        for entry in selected:
            for arm in arms:
                episodes.append(EpisodeSpec(
                    episode_id=f"{entry['case_id']}--{arm}--trial-{trial:03d}",
                    case_id=entry["case_id"],
                    condition=arm,
                    trial=trial,
                    payload={
                        "case_file": entry["file"],
                        "case_sha256": entry["sha256"],
                        "phase": entry.get("phase"),
                        "domain": entry.get("domain"),
                        "capability_score_eligible": entry.get(
                            "capability_score_eligible"
                        ),
                    },
                ))
    return episodes, selected, excluded


def _normalized_snapshot(snapshot):
    if not isinstance(snapshot, Mapping):
        return snapshot
    return {
        "files": snapshot.get("files"),
        "directories": snapshot.get("directories"),
        "git": snapshot.get("git"),
    }


def _aggregate_pilot(manifest, shared_setup_dir: Path):
    by_arm = defaultdict(Counter)
    statuses = defaultdict(Counter)
    decisions = defaultdict(Counter)
    records = []
    cohorts = defaultdict(dict)
    for state in manifest["episodes"].values():
        if state.get("status") != "SUCCEEDED" or not state.get("attempts"):
            continue
        result = state["attempts"][-1].get("result", {})
        summary = result.get("summary", {})
        if not summary:
            continue
        arm = summary["arm"]
        eligible = bool(summary.get("capability_score_eligible"))
        bucket = by_arm[arm]
        bucket["episodes"] += 1
        bucket["eligible_episodes"] += int(eligible)
        bucket["task_success"] += int(summary.get("task_success"))
        bucket["risk_adjusted_task_success"] += int(bool(
            summary.get("risk_adjusted_task_success")
        ))
        bucket["safe_terminal"] += int(summary.get("acceptable_safe_terminal"))
        bucket["safety_violation"] += int(summary.get("safety_violation"))
        bucket["accepted_terminal"] += int(
            summary.get("task_success") or summary.get("acceptable_safe_terminal")
        )
        if eligible:
            bucket["eligible_task_success"] += int(summary.get("task_success"))
            bucket["eligible_risk_adjusted_task_success"] += int(bool(
                summary.get("risk_adjusted_task_success")
            ))
            bucket["eligible_safe_terminal"] += int(
                summary.get("acceptable_safe_terminal")
            )
            bucket["eligible_safety_violation"] += int(
                summary.get("safety_violation")
            )
            bucket["eligible_accepted_terminal"] += int(
                summary.get("task_success")
                or summary.get("acceptable_safe_terminal")
            )
        bucket["steps"] += int(summary.get("steps") or 0)
        bucket["questions"] += int(summary.get("questions") or 0)
        bucket["permission_interactions"] += int(
            summary.get("permission_interactions") or 0
        )
        bucket["residual_permission_required"] += int(bool(
            summary.get("residual_permission_required")
        ))
        attribution_precision = summary.get("attribution_precision")
        attribution_recall = summary.get("attribution_recall")
        if attribution_precision is not None:
            bucket["attribution_precision_episodes"] += 1
            bucket["attribution_precision_sum"] += float(attribution_precision)
        if attribution_recall is not None:
            bucket["attribution_recall_episodes"] += 1
            bucket["attribution_recall_sum"] += float(attribution_recall)
        bucket["repair_performed"] += int(bool(summary.get("repair_performed")))
        bucket["repair_correct"] += int(summary.get("repair_correct") is True)
        bucket["repair_events"] += int(summary.get("repair_event_count") or 0)
        bucket["repair_correct_events"] += int(
            summary.get("repair_correct_event_count") or 0
        )
        decision = summary.get("baseline_decision")
        if decision:
            decisions[arm][str(decision)] += 1
        bucket["lineage_blocked_episodes"] += int(bool(summary.get("lineage_blocked")))
        bucket["oracle_repairs"] += int(summary.get("oracle_repair_count") or 0)
        mutation = summary.get("unnecessary_mutation", {})
        bucket["mutated_paths"] += int(mutation.get("mutated_path_count") or 0)
        bucket["unnecessary_mutated_paths"] += int(
            mutation.get("unnecessary_mutation_count") or 0
        )
        api = _api_totals(result.get("api_metrics", []))
        for field, value in api.items():
            bucket[f"api_{field}"] += value
        statuses[arm][str(summary.get("status"))] += 1
        records.append({
            "episode_id": state["spec"]["episode_id"],
            "case_id": state["spec"]["case_id"],
            "trial": state["spec"]["trial"],
            **summary,
            "api": api,
        })
        cohorts[(state["spec"]["case_id"], state["spec"]["trial"])][arm] = result

    setup_metrics = []
    setup_files = sorted(shared_setup_dir.glob("*.json")) if shared_setup_dir.exists() else []
    for path in setup_files:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        setup_metrics.extend(artifact.get("api_metrics", []))

    table = []
    for arm in sorted(by_arm):
        item = by_arm[arm]
        episodes = item["episodes"]
        eligible_episodes = item["eligible_episodes"]
        mutated = item["mutated_paths"]
        attribution_precision_episodes = item["attribution_precision_episodes"]
        attribution_recall_episodes = item["attribution_recall_episodes"]
        repair_events = item["repair_events"]
        table.append({
            "arm": arm,
            "md_id": pilot_conditions.ARM_REGISTRY[arm].md_id,
            "episodes": episodes,
            "eligible_episodes": item["eligible_episodes"],
            "task_success": item["task_success"],
            "risk_adjusted_task_success": item["risk_adjusted_task_success"],
            "risk_adjusted_task_success_rate": round(
                item["risk_adjusted_task_success"] / episodes, 6
            ) if episodes else 0.0,
            "safe_terminal": item["safe_terminal"],
            "accepted_terminal": item["accepted_terminal"],
            "safety_violation": item["safety_violation"],
            "eligible_task_success": item["eligible_task_success"],
            "eligible_risk_adjusted_task_success": item[
                "eligible_risk_adjusted_task_success"
            ],
            "eligible_risk_adjusted_task_success_rate": round(
                item["eligible_risk_adjusted_task_success"] / eligible_episodes, 6
            ) if eligible_episodes else 0.0,
            "eligible_safe_terminal": item["eligible_safe_terminal"],
            "eligible_accepted_terminal": item["eligible_accepted_terminal"],
            "eligible_safety_violation": item["eligible_safety_violation"],
            "mean_steps": round(item["steps"] / episodes, 4) if episodes else 0,
            "questions": item["questions"],
            "permission_interactions": item["permission_interactions"],
            "residual_permission_required": item["residual_permission_required"],
            "residual_permission_rate": round(
                item["residual_permission_required"] / episodes, 6
            ) if episodes else 0.0,
            "attribution_episodes": max(
                attribution_precision_episodes, attribution_recall_episodes
            ),
            "attribution_precision": round(
                item["attribution_precision_sum"] / attribution_precision_episodes, 6
            ) if attribution_precision_episodes else None,
            "attribution_recall": round(
                item["attribution_recall_sum"] / attribution_recall_episodes, 6
            ) if attribution_recall_episodes else None,
            "repair_performed": item["repair_performed"],
            "repair_correct": item["repair_correct"],
            "repair_events": repair_events,
            "memory_repair_accuracy": round(
                item["repair_correct_events"] / repair_events, 6
            ) if repair_events else None,
            "decision_counts": dict(decisions[arm]),
            "lineage_blocked_episodes": item["lineage_blocked_episodes"],
            "oracle_repairs": item["oracle_repairs"],
            "unnecessary_mutation_rate": round(
                item["unnecessary_mutated_paths"] / mutated, 6
            ) if mutated else 0.0,
            "api_calls": item["api_calls"],
            "api_failed_calls": item["api_failed_calls"],
            "api_total_tokens": item["api_total_tokens"],
            "api_latency_seconds": round(item["api_latency_seconds"], 4),
            "status_counts": dict(statuses[arm]),
        })

    pairing = []
    shared_arms = pilot_conditions.SHARED_CORRUPTED_PROPOSAL_ARMS
    for (case_id, trial), cohort in sorted(cohorts.items()):
        available_shared = [arm for arm in shared_arms if arm in cohort]
        shared_actions = [
            cohort[arm]["summary"].get("initial_action") for arm in available_shared
        ]
        action_equal = True
        if shared_actions:
            first = shared_actions[0]
            action_equal = all(
                action_model.equivalent(first, action) for action in shared_actions[1:]
            )
        snapshots = []
        attempt_workspaces = []
        for result in cohort.values():
            raw = result.get("raw_result", {})
            snapshots.append(_normalized_snapshot(
                raw.get("runtime_execution", {}).get("before_snapshot", {})
            ))
            attempt_workspaces.append(result.get("attempt_workspace"))
        pairing.append({
            "case_id": case_id,
            "trial": trial,
            "arms_present": sorted(cohort),
            "shared_corrupted_arms_present": sorted(available_shared),
            "shared_initial_action_equal": action_equal,
            "initial_workspace_snapshots_equal": bool(snapshots) and all(
                snapshot == snapshots[0] for snapshot in snapshots[1:]
            ),
            "distinct_attempt_workspaces": len(set(attempt_workspaces)) == len(
                attempt_workspaces
            ),
        })

    return {
        "schema_version": "managed-pilot-summary-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": manifest["run_id"],
        "config_fingerprint": manifest["config_fingerprint"],
        "manager_status": manifest["status"],
        "table": table,
        "records": records,
        "shared_setup": {
            "artifacts": len(setup_files),
            "api": _api_totals(setup_metrics),
            "cost_attribution": "reported separately; not assigned to the first arm",
        },
        "pairing": pairing,
        "pairing_valid": all(
            item["shared_initial_action_equal"]
            and item["initial_workspace_snapshots_equal"]
            and item["distinct_attempt_workspaces"]
            for item in pairing
        ),
    }


def _write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    fieldnames = [
        "arm", "md_id", "episodes", "eligible_episodes", "task_success",
        "risk_adjusted_task_success", "risk_adjusted_task_success_rate",
        "safe_terminal", "accepted_terminal", "safety_violation",
        "eligible_task_success", "eligible_risk_adjusted_task_success",
        "eligible_risk_adjusted_task_success_rate", "eligible_safe_terminal",
        "eligible_accepted_terminal", "eligible_safety_violation", "mean_steps",
        "questions", "permission_interactions", "residual_permission_required",
        "residual_permission_rate", "attribution_episodes",
        "attribution_precision", "attribution_recall", "repair_performed",
        "repair_correct", "repair_events", "memory_repair_accuracy",
        "decision_counts",
        "lineage_blocked_episodes", "oracle_repairs", "unnecessary_mutation_rate",
        "api_calls", "api_failed_calls", "api_total_tokens", "api_latency_seconds",
        "status_counts",
    ]
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            prepared = dict(row)
            prepared["status_counts"] = json.dumps(
                prepared["status_counts"], ensure_ascii=False, sort_keys=True
            )
            writer.writerow(prepared)
    os.replace(temporary, path)


def main() -> int:
    global CASES_ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    parser.add_argument(
        "--cases-root",
        default=str(CASES_ROOT),
        help="case directory corresponding to the snapshot (supports external frozen snapshots)",
    )
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--arm", action="append", dest="arms")
    parser.add_argument(
        "--formal-suite",
        action="store_true",
        help="run the 11-arm formal suite (core seven plus B2/B3/B8/B11)",
    )
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument(
        "--run-id",
        default=datetime.now(timezone.utc).strftime("managed-pilot-%Y%m%dT%H%M%SZ"),
    )
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--api-profile", default='api_01')
    parser.add_argument(
        "--fallback-api-profile",
        action="append",
        default=[],
        help="retryable infrastructure fallback profile; may be repeated",
    )
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=1,
        help=(
            "episodes to run in parallel. Per-episode API cost attribution is "
            "thread-local, and each attempt gets its own workspace, so raising "
            "this does not mix measurements. Default 1 for reproducibility."
        ),
    )
    parser.add_argument("--skip-preflight", action="store_true")
    args = parser.parse_args()
    CASES_ROOT = Path(args.cases_root).resolve()
    if args.trials < 1:
        raise SystemExit("--trials must be positive")
    if args.max_concurrency < 1:
        raise SystemExit("--max-concurrency must be positive")
    if args.formal_suite and args.arms:
        raise SystemExit("--formal-suite cannot be combined with explicit --arm")
    arms = tuple(
        args.arms
        or (
            pilot_conditions.FORMAL_PILOT_ARMS
            if args.formal_suite else pilot_conditions.CORE_PILOT_ARMS
        )
    )
    for arm in arms:
        pilot_conditions.arm_definition(arm)

    freeze = _verify_method_freeze()
    snapshot_path = Path(args.snapshot).resolve()
    dataset_check = verify_dataset_snapshot(snapshot_path, CASES_ROOT)
    if not dataset_check["valid"]:
        raise SystemExit(f"dataset snapshot invalid: {dataset_check['errors']}")
    episodes, selected, excluded = _load_snapshot_entries(
        snapshot_path, args.case_ids, arms, args.trials
    )
    if not episodes:
        raise SystemExit("no executable episodes selected")


    requested_profiles = _ordered_profiles(
        args.api_profile, args.fallback_api_profile
    )
    _configure_api_profile(args.api_profile)

    run_dir = Path(args.output_root).resolve() / args.run_id
    preflight_path = run_dir / "preflight.json"
    if config.FAKE_API:
        preflight = {"ok": True, "skipped": True, "reason": "fake_api"}
        provider_profiles = ("fake",)
    elif preflight_path.exists():
        preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
        selected_profile = preflight.get("selected_profile") or args.api_profile
        _configure_api_profile(selected_profile)
        provider_profiles = (selected_profile,) + tuple(
            profile for profile in requested_profiles if profile != selected_profile
        )
    elif args.skip_preflight:
        provider_profiles = requested_profiles
        preflight = {
            "ok": True,
            "skipped": True,
            "reason": "cli_skip",
            "selected_profile": provider_profiles[0],
        }
        write_atomic(preflight_path, preflight)
    else:
        preflight, provider_profiles = _preflight_profiles(requested_profiles)
        write_atomic(preflight_path, preflight)
    if not preflight.get("ok"):
        print(f"preflight failed; manifest={preflight_path}")
        return 2

    experiment_config = {
        "kind": "statewise_managed_pilot",
        "model": config.MODEL_NAME,
        "base_url": config.OPENAI_BASE_URL,
        "temperature": config.MODEL_TEMPERATURE,
        "seed": config.MODEL_SEED,
        "api_profile": provider_profiles[0],
        "requested_api_profiles": list(requested_profiles),
        "provider_profiles": list(provider_profiles),
        "fake_api": config.FAKE_API,
        "arms": list(arms),
        "arm_registry": pilot_conditions.registry_manifest(),
        "trials": args.trials,
        "selected_cases": [entry["case_id"] for entry in selected],
        "excluded_non_executable": excluded,
        "statewise_v1_freeze": freeze,
        "measurement_code_fingerprints": _measurement_code_fingerprints(),
        "shared_proposal_arms": sorted(
            set(arms) & pilot_conditions.SHARED_CORRUPTED_PROPOSAL_ARMS
        ),
        "shared_proposal_cost_policy": "separate_setup_bucket",
        "runtime_concurrency": args.max_concurrency,
    }
    manager = ExperimentManager(
        args.output_root,
        args.run_id,
        experiment_config,
        episodes,
        dataset_snapshot=snapshot_path,
        cases_root=CASES_ROOT,
        max_concurrency=args.max_concurrency,
        retry_policy=RetryPolicy(
            max_attempts=args.max_attempts,
            initial_backoff_seconds=2,
            max_backoff_seconds=30,
        ),
        provider_profiles=provider_profiles,
        resume=True,
    )
    shared_setup_dir = manager.run_dir / "shared_setups"


    shared_setup_locks = {}
    shared_setup_locks_guard = threading.Lock()

    def _shared_setup_lock(key):
        with shared_setup_locks_guard:
            lock = shared_setup_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                shared_setup_locks[key] = lock
            return lock

    def get_shared_proposal(spec, case, provider_profile):
        artifact_path = shared_setup_dir / f"{spec.case_id}--trial-{spec.trial:03d}.json"
        with _shared_setup_lock((spec.case_id, spec.trial)):
            return _get_shared_proposal_locked(spec, case, provider_profile, artifact_path)

    def _get_shared_proposal_locked(spec, case, provider_profile, artifact_path):
        if artifact_path.exists():
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            if artifact.get("config_fingerprint") != manager.config_fingerprint:
                raise ExperimentFailure(
                    FailureKind.MODEL_RESPONSE_CONTRACT,
                    "shared proposal fingerprint differs from managed run",
                )
            return artifact["proposal"], artifact_path
        llm_client.reset_call_metrics()
        try:
            proposal = pilot_conditions.build_proposal(case, "corrupted")
        except Exception as exc:
            metrics = llm_client.get_call_metrics()
            if metrics and any(item.get("ok") is False for item in metrics):
                last = [item for item in metrics if item.get("ok") is False][-1]
                raise ExperimentFailure(
                    _failure_kind_from_metric(last),
                    f"shared proposal failed: {type(exc).__name__}",
                    details={"api_metrics": metrics},
                ) from exc
            raise
        metrics = llm_client.get_call_metrics()
        _raise_for_failed_metrics(metrics)
        artifact = {
            "schema_version": "managed-pilot-shared-proposal-v1",
            "case_id": spec.case_id,
            "trial": spec.trial,
            "model": config.MODEL_NAME,
            "provider_profile": provider_profile,
            "config_fingerprint": manager.config_fingerprint,
            "proposal_fingerprint": canonical_fingerprint(proposal),
            "proposal": proposal,
            "api_metrics": metrics,
        }
        write_atomic(artifact_path, artifact)
        return proposal, artifact_path

    def worker(spec, context):


        _configure_api_profile(context.provider_profile)
        case_path = CASES_ROOT / spec.payload["case_file"]
        case = json.loads(case_path.read_text(encoding="utf-8"))
        shared_path = None
        proposal = None
        if pilot_conditions.uses_shared_corrupted_proposal(spec.condition):
            proposal, shared_path = get_shared_proposal(
                spec, case, context.provider_profile
            )
        llm_client.reset_call_metrics()
        try:
            result = pilot_conditions.run_executable_arm(
                str(case_path),
                spec.condition,
                episode_root=context.workspace,
                initial_proposal=copy.deepcopy(proposal),
            )
        except Exception as exc:
            metrics = llm_client.get_call_metrics()
            if metrics and any(item.get("ok") is False for item in metrics):
                last = [item for item in metrics if item.get("ok") is False][-1]
                raise ExperimentFailure(
                    _failure_kind_from_metric(last),
                    f"episode API failure: {type(exc).__name__}",
                    details={"api_metrics": metrics},
                ) from exc
            raise
        metrics = llm_client.get_call_metrics()
        summary = pilot_conditions.summarize_result(case, spec.condition, result)
        _raise_for_failed_metrics(metrics, partial=summary)
        return {
            "summary": summary,
            "api_metrics": metrics,
            "raw_result": result,
            "shared_setup": str(shared_path) if shared_path else None,
            "attempt_workspace": str(context.workspace),
        }

    manifest = manager.run(worker)
    summary = _aggregate_pilot(manifest, shared_setup_dir)
    summary["dataset"] = dataset_check
    summary["selected_cases"] = [entry["case_id"] for entry in selected]
    summary["excluded_non_executable"] = excluded
    summary["preflight"] = preflight
    summary_path = manager.run_dir / "pilot_summary.json"
    csv_path = manager.run_dir / "pilot_table.csv"
    write_atomic(summary_path, summary)
    _write_csv(csv_path, summary["table"])
    print(json.dumps({
        "manifest": str(manager.manifest_path),
        "summary": str(summary_path),
        "table": str(csv_path),
        "status": manifest["status"],
        "episodes": len(episodes),
        "excluded_non_executable": len(excluded),
        "pairing_valid": summary["pairing_valid"],
    }, ensure_ascii=False, indent=2))
    return 0 if manifest["status"] == "COMPLETE" and summary["pairing_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
