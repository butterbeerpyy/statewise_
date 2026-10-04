from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scaffold.runners import method_freeze_v1
from scaffold.runners.run_managed_pilot import (
    _configure_api_profile,
    _failure_kind_from_metric,
    _ordered_profiles,
    _preflight_profiles,
    _raise_for_failed_metrics,
)
from scaffold.statewise import config
from scaffold.statewise.agents import llm_client
from scaffold.statewise.evaluation import measurement
from scaffold.statewise.evaluation.longitudinal_runtime import (
    initial_memory_for_arm,
    materialize_case,
    memory_contract,
    memory_fingerprint,
    run_arm_task,
    smoke_preflight,
)
from scaffold.statewise.evaluation.longitudinal_schema import (
    canonical_sha256,
    load_dataset,
    validate_dataset,
)
from scaffold.statewise.experiments import pilot_conditions
from scaffold.statewise.experiments.experiment_manager import (
    DEFAULT_RETRYABLE_FAILURES,
    EpisodeSpec,
    ExperimentFailure,
    ExperimentManager,
    FailureKind,
    RetryPolicy,
    write_atomic,
)
from scaffold.statewise.memory import memory_store


DEFAULT_DATASET = ROOT / "scaffold" / "experiments" / "rq5_longitudinal_20_v1"
DEFAULT_OUTPUT_ROOT = ROOT / "runs" / "rq5_longitudinal"
MEASUREMENT_FILES = (
    "scaffold/runners/run_rq5_longitudinal_real.py",
    "scaffold/statewise/evaluation/longitudinal_runtime.py",
    "scaffold/statewise/evaluation/longitudinal_schema.py",
    "scaffold/statewise/experiments/pilot_conditions.py",
    "scaffold/statewise/runtime/lightweight_runtime.py",
    "scaffold/statewise/runtime/structured_mutation_runtime.py",
)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dataset_integrity(directory: Path) -> dict[str, Any]:
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors = []
    seen = set()
    for entry in manifest.get("files", []):
        path = (directory / entry.get("path", "")).resolve()
        try:
            path.relative_to(directory.resolve())
        except ValueError:
            errors.append(f"path escapes dataset: {entry.get('path')}")
            continue
        if not path.is_file():
            errors.append(f"missing sequence: {entry.get('path')}")
            continue
        sequence = json.loads(path.read_text(encoding="utf-8"))
        actual = canonical_sha256(sequence)
        if actual != entry.get("sha256"):
            errors.append(f"sequence hash mismatch: {entry.get('path')}")
        seen.add(path.name)
    actual_files = {path.name for path in directory.glob("seq_*.json")}
    if actual_files != seen:
        errors.append("manifest membership differs from seq_*.json files")
    expected_composite = canonical_sha256(manifest.get("files", []))
    if expected_composite != manifest.get("composite_sha256"):
        errors.append("manifest composite_sha256 mismatch")
    schema = validate_dataset(load_dataset(directory))
    errors.extend(schema.get("errors", []))
    return {
        "valid": not errors,
        "dataset_id": manifest.get("dataset_id"),
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": _file_sha256(manifest_path),
        "composite_sha256": manifest.get("composite_sha256"),
        "schema": schema,
        "errors": errors,
    }


def _selected_sequences(directory: Path, selected_ids: list[str] | None):
    sequences = load_dataset(directory)
    if not selected_ids:
        return sequences
    by_id = {item["sequence_id"]: item for item in sequences}
    missing = sorted(set(selected_ids) - set(by_id))
    if missing:
        raise ValueError(f"unknown sequence ids: {missing}")
    return [by_id[item] for item in selected_ids]


def _fake_action_for_state(case, state):
    correct = copy.deepcopy(case["execution"]["smoke_action"])
    wrong = copy.deepcopy(case.get("safety", {}).get("unsafe_action") or correct)
    key = case["memory_key"]
    serving = memory_store.find_by_key(
        state, key, scope=case.get("environment", {}).get("scope")
    )
    if serving is None:
        return correct, wrong, True, None
    is_correct = measurement.semantic_equal(
        serving.get("value"), case["ground_truth_state"]["value"]
    )
    return (correct if is_correct else wrong), (wrong if is_correct else correct), is_correct, serving


def _install_fake_responses(case, state):

    case_id = case["case_id"]
    action, alternative, is_correct, serving = _fake_action_for_state(case, state)
    correct = copy.deepcopy(case["execution"]["smoke_action"])
    wrong = copy.deepcopy(case.get("safety", {}).get("unsafe_action") or correct)
    rationale = (
        f"Use persistent {case['memory_key']} to select the task action."
    )
    proposal = {"action": action, "rationale": rationale}
    correct_proposal = {"action": correct, "rationale": rationale}
    for suffix in (
        "propose_action_initial",
        "propose_action_initial_correct",
        "propose_action_initial_no_memory",
        "replan_final",
        "replan_final_correct",
    ):
        llm_client.FAKE_RESPONSES[f"{case_id}:{suffix}"] = copy.deepcopy(
            correct_proposal if suffix != "propose_action_initial" or is_correct else proposal
        )
    for arm in pilot_conditions.ARM_REGISTRY:
        for step in range(1, 9):
            llm_client.FAKE_RESPONSES[
                f"{case_id}:episode_step_{step}_{arm}"
            ] = copy.deepcopy(correct_proposal)
            llm_client.FAKE_RESPONSES[
                f"{case_id}:episode_step_{step}"
            ] = copy.deepcopy(correct_proposal)
            llm_client.FAKE_RESPONSES[
                f"{case_id}:episode_step_{step}_correct"
            ] = copy.deepcopy(correct_proposal)
            llm_client.FAKE_RESPONSES[
                f"{case_id}:safety_sentry_step_{step}"
            ] = {
                "decision": "direct_execute",
                "reasoning": "deterministic fake plumbing fixture",
                "question": None,
            }
    llm_client.FAKE_RESPONSES[f"{case_id}:safety_sentry_initial"] = {
        "decision": "direct_execute",
        "reasoning": "deterministic fake plumbing fixture",
        "question": None,
    }

    current_id = serving.get("id") if serving else None
    repaired_id = current_id if is_correct and current_id else "M1"
    for suffix, memory_id, value, alt_action in (
        ("", current_id or "RQ5_CORRUPTED", serving.get("value") if serving else None, alternative),
        ("_correct", repaired_id, case["ground_truth_state"]["value"], wrong),
    ):
        claim_value = value if value is not None else case["ground_truth_state"]["value"]
        llm_client.FAKE_RESPONSES[f"{case_id}:extract_states{'_correct' if suffix else ''}"] = {
            "support_states": [{
                "id": "S1",
                "claim": f"{case['memory_key']} = {claim_value}",
                "source": f"memory:{memory_id}",
                "confidence": "medium",
                "relation": "used_to_fill_argument",
                "supported_argument": "target",
            }]
        }
        llm_client.FAKE_RESPONSES[f"{case_id}:alt_value_S1{suffix}"] = {
            "alt_values": [case["ground_truth_state"]["value"]]
            if not measurement.semantic_equal(claim_value, case["ground_truth_state"]["value"])
            else [case["corrupted_state"]["value"]]
        }
        llm_client.FAKE_RESPONSES[f"{case_id}:counterfactual_S1{suffix}"] = {
            "action": copy.deepcopy(alt_action),
            "rationale": "Counterfactual state selects the opposite task target.",
        }


def _task_record(sequence, task, arm, state, previous_after, task_root):
    case = materialize_case(sequence, task)
    if config.FAKE_API:
        case["case_id"] = f"{case['case_id']}__fake__{arm}"
        _install_fake_responses(case, state)
    before = memory_fingerprint(state)
    before_contract = memory_contract(sequence, state)
    result = run_arm_task(case, state, arm, task_root)
    returned_state = result.get("final_memory")
    final_state = copy.deepcopy(state if returned_state is None else returned_state)
    after = memory_fingerprint(final_state)
    after_contract = memory_contract(sequence, final_state)
    summary = pilot_conditions.summarize_result(case, arm, result)
    context_ids = set(str(item) for item in result.get("planner_context_memory_ids", []))
    repaired_id = before_contract.get("active_memory_id")
    record = {
        "task_id": task["task_id"],
        "task_index": task["task_index"],
        "memory_before": before,
        "memory_after": after,
        "inherited_previous_final_exactly": (
            True if previous_after is None else before == previous_after
        ),
        "runtime_received_initial_state_exactly": (
            memory_fingerprint(result.get("initial_memory") or {}) == before
        ),
        "memory_contract_before": before_contract,
        "memory_contract_after": after_contract,
        "repaired_memory_entered_planner_context": bool(
            repaired_id and before_contract["repaired_contract_satisfied"]
            and repaired_id in context_ids
        ),
        "summary": summary,
    }
    if not config.FAKE_API:
        record["raw_result"] = result
    return final_state, record


def _sequence_metrics(arm, tasks):
    future = tasks[1:]
    future_success = sum(item["summary"]["task_success"] for item in future)
    future_no_violation = sum(
        not item["summary"]["safety_violation"] for item in future
    )
    future_safe_completion = sum(
        item["summary"]["risk_adjusted_task_success"] for item in future
    )
    inherited = sum(item["inherited_previous_final_exactly"] for item in future)
    reused = sum(item["repaired_memory_entered_planner_context"] for item in future)
    repeated = sum(item["summary"]["repair_performed"] for item in future)
    return {
        "arm": arm,
        "tasks": len(tasks),
        "task_success_count": sum(item["summary"]["task_success"] for item in tasks),
        "task_success_rate": sum(item["summary"]["task_success"] for item in tasks) / len(tasks),
        "future_task_success_count": future_success,
        "future_task_success_rate": future_success / len(future),
        "future_no_violation_rate": future_no_violation / len(future),
        "future_safe_completion_rate": future_safe_completion / len(future),
        "state_handoff_integrity_rate": inherited / len(future),
        "state_reuse_rate": reused / len(future),
        "repeated_intervention_count": repeated,
        "repeated_intervention_rate": repeated / len(future),
        "cumulative_questions": sum(item["summary"]["questions"] for item in tasks),
        "cumulative_permission_interactions": sum(
            item["summary"]["permission_interactions"] for item in tasks
        ),
        "cumulative_safety_violations": sum(
            item["summary"]["safety_violation"] for item in tasks
        ),
        "t1_repaired_contract_satisfied": tasks[0]["memory_contract_after"][
            "repaired_contract_satisfied"
        ],
    }


def _aggregate(manifest):
    rows = []
    failures = Counter()
    for state in manifest["episodes"].values():
        if state.get("status") != "SUCCEEDED":
            failures[state.get("status", "UNKNOWN")] += 1
            continue
        result = state["attempts"][-1].get("result", {})
        metrics = result.get("metrics")
        if metrics:
            rows.append({
                "sequence_id": result.get("sequence_id"),
                "trial": state["spec"]["trial"],
                **metrics,
            })
    by_arm = defaultdict(list)
    for row in rows:
        by_arm[row["arm"]].append(row)
    table = []
    rate_fields = (
        "task_success_rate",
        "future_task_success_rate",
        "future_no_violation_rate",
        "future_safe_completion_rate",
        "state_handoff_integrity_rate",
        "state_reuse_rate",
        "repeated_intervention_rate",
    )
    for arm, items in sorted(by_arm.items()):
        row = {"arm": arm, "sequences": len(items)}
        for field in rate_fields:
            row[field] = round(sum(item[field] for item in items) / len(items), 6)
        for field in (
            "cumulative_questions",
            "cumulative_permission_interactions",
            "cumulative_safety_violations",
        ):
            row[field] = sum(item[field] for item in items)
        row["t1_repair_success_rate"] = round(
            sum(item["t1_repaired_contract_satisfied"] for item in items) / len(items), 6
        )
        table.append(row)
    return {
        "schema_version": "rq5-longitudinal-summary-v1",
        "run_id": manifest["run_id"],
        "status": manifest["status"],
        "sequence_arm_results": rows,
        "table": table,
        "failed_episode_statuses": dict(failures),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("sequences", type=Path, nargs="?", default=DEFAULT_DATASET)
    parser.add_argument("--run-id", default=f"rq5-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--sequence-id", action="append", dest="sequence_ids")
    parser.add_argument("--arm", action="append", dest="arms")
    parser.add_argument("--formal-suite", action="store_true")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--api-profile", default="fake")
    parser.add_argument("--fallback-api-profile", action="append", default=[])
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument(
        "--retry-response-contract",
        action="store_true",
        help=(
            "Also retry episodes that failed because the provider returned "
            "unparseable JSON. Malformed output is a provider-side transport "
            "defect rather than a method outcome, but retrying it is opt-in so "
            "the default policy keeps measuring the model as-is."
        ),
    )
    args = parser.parse_args()

    if min(args.trials, args.max_concurrency, args.max_attempts) < 1:
        raise SystemExit("trials, max-concurrency, and max-attempts must be positive")
    retryable_failures = DEFAULT_RETRYABLE_FAILURES
    if args.retry_response_contract:
        retryable_failures = retryable_failures | {FailureKind.MODEL_RESPONSE_CONTRACT}
    dataset_dir = args.sequences.resolve()
    integrity = _dataset_integrity(dataset_dir)
    if not integrity["valid"]:
        raise SystemExit(f"RQ5 dataset integrity failed: {integrity['errors']}")
    sequences = _selected_sequences(dataset_dir, args.sequence_ids)
    arms = tuple(args.arms or pilot_conditions.FORMAL_PILOT_ARMS)
    if args.formal_suite and args.arms:
        raise SystemExit("--formal-suite cannot be combined with --arm")
    for arm in arms:
        pilot_conditions.arm_definition(arm)

    preflight = []
    if not args.skip_preflight:
        for sequence in sequences:
            for task in sequence["tasks"]:
                case = materialize_case(sequence, task)
                preflight.append({
                    "sequence_id": sequence["sequence_id"],
                    "task_id": task["task_id"],
                    **smoke_preflight(case),
                })
    failures = [item for item in preflight if not item.get("ok")]
    if failures:
        raise SystemExit(f"RQ5 runtime preflight failed for {len(failures)} tasks")

    _configure_api_profile(args.api_profile)
    freeze = method_freeze_v1.verify()
    live = not config.FAKE_API
    if live and args.max_concurrency != 1:
        raise SystemExit(
            "live RQ5 runs require --max-concurrency 1 because method variant "
            "contexts are process-global; parallelize with isolated per-arm processes"
        )
    if live and "statewise_v1" in arms and not freeze["valid"]:
        raise SystemExit(
            "StateWise-v1 freeze is invalid; refusing a paid run against an unnamed method state"
        )
    if not args.execute:
        print(json.dumps({
            "ok": True,
            "mode": "preflight_only",
            "sequences": len(sequences),
            "tasks": sum(len(item["tasks"]) for item in sequences),
            "arms": list(arms),
            "runtime_preflight_failures": 0,
            "dataset": integrity,
            "statewise_v1_freeze": freeze,
        }, ensure_ascii=False, indent=2))
        return 0

    requested_profiles = _ordered_profiles(args.api_profile, args.fallback_api_profile)
    if config.FAKE_API:
        provider_profiles = ("fake",)
        provider_preflight = {"ok": True, "skipped": True, "reason": "fake_api"}
    else:
        provider_preflight, provider_profiles = _preflight_profiles(requested_profiles)
        if not provider_preflight.get("ok"):
            raise SystemExit("all requested API profiles failed preflight")

    by_id = {item["sequence_id"]: item for item in sequences}
    episodes = []
    for trial in range(args.trials):
        for sequence in sequences:
            sequence_hash = canonical_sha256(sequence)
            for arm in arms:
                episodes.append(EpisodeSpec(
                    episode_id=f"{sequence['sequence_id']}--{arm}--trial-{trial:03d}",
                    case_id=sequence["sequence_id"],
                    condition=arm,
                    trial=trial,
                    payload={
                        "sequence_id": sequence["sequence_id"],
                        "sequence_sha256": sequence_hash,
                        "domain": sequence["domain"],
                    },
                ))

    experiment_config = {
        "kind": "rq5_longitudinal_real",
        "schema_version": "rq5-longitudinal-run-v1",
        "model": config.MODEL_NAME,
        "api_profile": provider_profiles[0],
        "provider_profiles": list(provider_profiles),


        "temperature": config.effective_temperature(),
        "temperature_is_profile_override": config.MODEL_TEMPERATURE_OVERRIDE is not None,
        "fake_api": config.FAKE_API,
        "fake_data_policy": "plumbing_only_not_empirical" if config.FAKE_API else None,
        "arms": list(arms),
        "trials": args.trials,
        "sequences": [item["sequence_id"] for item in sequences],
        "dataset": integrity,
        "statewise_v1_freeze": freeze,
        "measurement_code_fingerprints": {
            relative: _file_sha256(ROOT / relative) for relative in MEASUREMENT_FILES
        },
        "provider_preflight": provider_preflight,
    }
    manager = ExperimentManager(
        args.output_root,
        args.run_id,
        experiment_config,
        episodes,
        max_concurrency=args.max_concurrency,
        retry_policy=RetryPolicy(
            max_attempts=args.max_attempts,
            retryable_failures=retryable_failures,
        ),
        provider_profiles=provider_profiles,
        resume=True,
    )

    def worker(spec, context):
        _configure_api_profile(context.provider_profile)
        sequence = by_id[spec.payload["sequence_id"]]
        if canonical_sha256(sequence) != spec.payload["sequence_sha256"]:
            raise RuntimeError("sequence changed after manager construction")
        llm_client.reset_call_metrics()
        state = initial_memory_for_arm(sequence, spec.condition)
        initial_fingerprint = memory_fingerprint(state)
        task_results = []
        previous_after = None
        try:
            for task in sequence["tasks"]:
                state, task_record = _task_record(
                    sequence,
                    task,
                    spec.condition,
                    state,
                    previous_after,
                    context.workspace / f"task-{task['task_index']}",
                )
                previous_after = task_record["memory_after"]
                task_results.append(task_record)
        except Exception as exc:
            metrics = llm_client.get_call_metrics()
            if metrics and any(item.get("ok") is False for item in metrics):
                failed = [item for item in metrics if item.get("ok") is False][-1]
                raise ExperimentFailure(
                    _failure_kind_from_metric(failed),
                    f"RQ5 sequence API failure: {type(exc).__name__}",
                    details={"api_metrics": metrics, "completed_tasks": len(task_results)},
                ) from exc
            raise
        metrics = llm_client.get_call_metrics()
        sequence_metrics = _sequence_metrics(spec.condition, task_results)
        _raise_for_failed_metrics(metrics, partial=sequence_metrics)
        return {
            "sequence_id": sequence["sequence_id"],
            "domain": sequence["domain"],
            "arm": spec.condition,
            "initial_memory_fingerprint": initial_fingerprint,
            "final_memory_fingerprint": memory_fingerprint(state),
            "final_memory_contract": memory_contract(sequence, state),
            "tasks": task_results,
            "metrics": sequence_metrics,
            "api_metrics": metrics,
            "attempt_workspace": str(context.workspace),
        }

    manifest = manager.run(worker)
    summary = _aggregate(manifest)
    summary.update({"dataset": integrity, "provider_preflight": provider_preflight})
    summary_path = manager.run_dir / "longitudinal_summary.json"
    write_atomic(summary_path, summary)
    print(json.dumps({
        "status": manifest["status"],
        "episodes": len(episodes),
        "manager_episodes": manager.aggregate(),
        "manifest": str(manager.manifest_path),
        "summary": str(summary_path),
        "table": summary["table"],
    }, ensure_ascii=False, indent=2))
    return 0 if manifest["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
