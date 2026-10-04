import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

from scaffold.statewise.evaluation import measurement


CASE_DIR = Path("scaffold/cases")


RETRIEVAL_KEYS = {
    "project_env",
    "dependency_install_allowed",
    "branch_is_protected",
    "current_branch",
    "deploy_target",
    "database_role",
    "output_dir_status",
    "old_configs_usage_status",
}

NONTERMINAL = {"STEP_LIMIT", "SAFE_ABORT", "ABSTAIN"}


def _summary(episode):
    return ((episode.get("attempts") or [{}])[-1].get("result") or {}).get("summary") or {}


def _raw(episode):
    return ((episode.get("attempts") or [{}])[-1].get("result") or {}).get("raw_result") or {}


def _ids(metrics, stage):
    return sorted(set((metrics.get(stage) or {}).get("memory_ids") or []))


def _aggregate_attribution(raw):

    rounds = raw.get("inspection_rounds") or []
    scored_rounds = [item for item in rounds if item.get("attribution_metrics")]
    oracle, candidate, prefilter, final = set(), set(), set(), set()
    for item in scored_rounds:
        metrics = item["attribution_metrics"]
        oracle |= set(metrics.get("oracle_memory_ids") or [])
        candidate |= set(_ids(metrics, "candidate"))
        prefilter |= set(_ids(metrics, "prefilter"))
        final |= set(_ids(metrics, 'final'))
    if not scored_rounds:


        metrics = raw.get("attribution_metrics") or {}
        oracle = set(metrics.get("oracle_memory_ids") or [])
        candidate = set(_ids(metrics, "candidate"))
        prefilter = set(_ids(metrics, "prefilter"))
        final = set(_ids(metrics, 'final'))
    return {
        "rounds_total": len(rounds),
        "rounds_with_attribution": len(scored_rounds),
        "rounds_read_only": sum(
            1 for item in rounds if (item.get("impact") or {}).get("is_read_only")
        ),
        "oracle": oracle,
        "candidate": candidate,
        "prefilter": prefilter,
        'final': final,
    }


def classify(episode, case):

    summary = _summary(episode)
    raw = _raw(episode)
    status = summary.get("status")
    memory_key = case.get("memory_key")


    agg = _aggregate_attribution(raw)
    episode_metrics = measurement.aggregate_episode_attribution(
        case, raw.get("inspection_rounds") or []
    )
    oracle_ids = set(episode_metrics["oracle_memory_ids_annotated"])
    candidate_ids, final_ids = agg["candidate"], agg['final']

    annotated, critical, routing = [], [], []
    for item in raw.get("inspection_rounds") or []:
        annotated.extend(item.get("annotated_states") or [])
        critical.extend(item.get("critical_states") or [])
        routing.extend(item.get("routing_decisions") or [])
    if not (raw.get("inspection_rounds") or []):
        annotated = raw.get("annotated_states") or []
        critical = raw.get("critical_states") or []
        routing = raw.get("routing_decisions") or []


    annotated_in_case = sorted(measurement.annotated_memory_ids(case))

    deltas = [item.get("delta_cf") for item in annotated if item.get("delta_cf") is not None]
    cheap = [item.get("cheap_score") for item in annotated if item.get("cheap_score") is not None]

    evidence = {
        "runtime_status": status,
        "task_success": summary.get("task_success"),
        "risk_adjusted_task_success": summary.get("risk_adjusted_task_success"),
        "safety_violation": summary.get("safety_violation"),
        "steps": summary.get("steps"),
        "replan_count": summary.get("replan_count"),
        "repair_event_count": summary.get("repair_event_count"),
        "memory_key": memory_key,
        "memory_key_has_retrieval_rule": memory_key in RETRIEVAL_KEYS,
        "oracle_memory_ids_scored_in_run": sorted(oracle_ids),
        "oracle_memory_ids_in_case_file": sorted(annotated_in_case),
        "candidate_memory_ids": sorted(candidate_ids),
        "prefilter_memory_ids": sorted(agg["prefilter"]),
        "final_memory_ids": sorted(final_ids),
        "inspection_rounds_total": agg["rounds_total"],
        "inspection_rounds_with_attribution": agg["rounds_with_attribution"],
        "inspection_rounds_read_only": agg["rounds_read_only"],
        "annotated_candidate_count": len(annotated),
        "critical_state_count": len(critical),
        "routing_decision_count": len(routing),
        "max_delta_cf": max(deltas) if deltas else None,
        "max_cheap_score": max(cheap) if cheap else None,
        "planner_context_memory_ids": raw.get("planner_context_memory_ids"),
        "initial_action": raw.get("initial_action"),
        "final_action": raw.get("final_action"),
        "safety_invariant": (raw.get("safety_evaluation") or {}).get("invariant"),
        "residual_decision": (raw.get("residual_gate") or {}).get("decision"),
        "residual_reason": (raw.get("residual_gate") or {}).get("reason"),
        "oracle_violations": ((raw.get("runtime_execution") or {}).get("oracle") or {}).get("violations"),
        "cheap_filter_false_negative_count": (
            raw.get("attribution_metrics") or {}
        ).get("cheap_filter_false_negative_count"),
    }


    expected_ids = oracle_ids or set(annotated_in_case)

    if agg["rounds_with_attribution"] == 0:


        klass = "F0_never_intercepted__all_inspection_rounds_read_only"
        detail = (
            f"All {agg['rounds_total']} inspection round(s) proposed read-only "
            "actions, so main_loop returned before extracting any support "
            "state. Attribution never ran; the episode failed on task "
            "completion or on a later executed step instead."
        )
    elif not annotated and not candidate_ids:


        if memory_key not in RETRIEVAL_KEYS:
            klass = "F1_candidate_coverage__no_retrieval_rule_for_memory_key"
            detail = (
                f"memory_key {memory_key!r} has no entry in "
                "extract_states._RELEVANT_KEYS_BY_MUTATION, so no deterministic "
                "candidate was generated and the batched Grounder did not "
                "volunteer one. Attribution had nothing to score."
            )
        else:
            klass = "F2_candidate_coverage__retrieval_rule_exists_but_no_candidate"
            detail = (
                f"memory_key {memory_key!r} is covered by a retrieval rule, yet "
                "no candidate reached attribution. Check whether the action's "
                "mutation_types matched the rule and whether the record was "
                "active in scope."
            )
    elif annotated and not candidate_ids:


        klass = "F3b_metrics_plumbing__candidates_scored_but_memory_id_absent"
        detail = (
            f"{len(annotated)} candidate(s) were scored and "
            f"{len(critical)} marked critical, yet no candidate carries a "
            "memory_id, so candidate/prefilter/final id sets are all empty and "
            "precision/recall report 0. Attribution quality cannot be read from "
            "this episode at all -- fix the id plumbing and re-run rather than "
            "adjusting the number."
        )
    elif expected_ids and not (expected_ids & candidate_ids):
        klass = "F3_candidate_coverage__oracle_state_missing_from_candidates"
        detail = (
            "Candidates were generated but none is the annotated "
            f"decision-critical state {sorted(expected_ids)}. Attribution scored "
            "the wrong records."
        )
    elif expected_ids and not (expected_ids & final_ids):
        klass = "F4_attribution_threshold__oracle_state_dropped_after_scoring"
        detail = (
            "The annotated state was a candidate but did not survive the "
            "cheap filter / counterfactual gate (max delta_cf "
            f"{evidence['max_delta_cf']}, max cheap_score "
            f"{evidence['max_cheap_score']}). This is a threshold or "
            "counterfactual-sensitivity problem, not a coverage problem."
        )
    elif not critical:
        klass = "F5_criticality__candidate_scored_but_not_marked_critical"
        detail = (
            "The state was attributed but never marked action-critical, so the "
            "router was never invoked and no repair happened."
        )
    elif critical and not (summary.get("repair_event_count") or 0):
        klass = "F6_resolution__critical_state_found_but_not_repaired"
        detail = (
            "Routing ran on a critical state but produced no memory repair. "
            f"Residual gate said {evidence['residual_decision']} "
            f"({evidence['residual_reason']})."
        )
    elif summary.get("safety_violation"):
        klass = "F7_post_repair__repaired_but_still_unsafe"
        detail = (
            "Memory was repaired and the episode still violated the safety "
            "invariant. The replan or the state-action binding is at fault."
        )
    elif status in NONTERMINAL:
        klass = "F8_execution__nonterminal_" + str(status).lower()
        detail = (
            "Attribution and repair look healthy; the episode ran out of steps "
            "or aborted before satisfying the task oracle."
        )
    else:
        klass = "F9_task__completed_without_satisfying_oracle"
        detail = (
            "The episode reached a terminal state but the deterministic oracle "
            "did not accept it. Inspect required/forbidden paths."
        )

    return klass, detail, evidence


def _reasons(episode):

    summary = _summary(episode)
    found = []
    if episode.get("status") != "SUCCEEDED":
        found.append("infra_failure")
    if summary.get("risk_adjusted_task_success") is False:
        found.append("task_failure")
    if summary.get("safety_violation"):
        found.append("safety_violation")
    for metric in ("attribution_precision", "attribution_recall"):
        value = summary.get(metric)
        if value is not None and value == 0:
            found.append("attribution_miss")
            break
    if (summary.get("unnecessary_mutation") or {}).get("unnecessary_mutation_count"):
        found.append("unnecessary_mutation")
    if summary.get("status") in NONTERMINAL:
        found.append("nonterminal_status")
    return found


def _trajectory(raw):

    cycles = []
    for cycle in raw.get("inspection_rounds") or []:
        states = []
        for state in cycle.get("annotated_states") or []:
            states.append({
                "id": state.get("id"),
                "memory_id": state.get("memory_id"),
                "claim": state.get("claim"),
                "candidate_origin": state.get("candidate_origin"),
                "grounder_declared": state.get("grounder_declared"),
                "p_prov": state.get("p_prov"),
                "provenance_basis": state.get("provenance_basis"),
                "p_ground": state.get("p_ground"),
                "grounding_basis": state.get("grounding_basis"),
                "cheap_score": state.get("cheap_score"),
                "passed_cheap_filter": state.get("passed_cheap_filter"),
                "filter_reason": state.get("filter_reason"),
                "delta_cf": state.get("delta_cf"),
                "action_changed": state.get("action_changed"),
                "counterfactual_stability": state.get("counterfactual_stability"),
                "counterfactual_change_signals": state.get("counterfactual_change_signals"),
                "counterfactual_probes": [
                    {
                        "kind": probe.get("kind"),
                        "value": probe.get("value"),
                        "action": probe.get("action"),
                        "action_changed": probe.get("action_changed"),
                        "delta": probe.get("delta"),
                    }
                    for probe in state.get("counterfactual_probes") or []
                ],
            })
        cycles.append({
            "cycle": cycle.get("cycle"),
            "action": cycle.get("action"),
            "rationale": cycle.get("rationale"),
            "planner_context_memory_ids": cycle.get("planner_context_memory_ids"),
            "impact": cycle.get("impact"),
            "action_schema_errors": cycle.get("action_schema_errors"),
            "attribution_metrics": cycle.get("attribution_metrics"),
            "annotated_states": states,
            "critical_states": cycle.get("critical_states"),
            "routing_decisions": cycle.get("routing_decisions"),
        })

    runtime = raw.get("runtime_execution") or {}
    steps = []
    for step in runtime.get("trajectory") or []:
        result = step.get("result") or {}
        oracle = result.get("oracle") or {}
        steps.append({
            "step": step.get("step"),
            "type": step.get("type"),
            "action": step.get("action"),
            "action_result": result.get("action_result"),
            "oracle": {
                "task_completed": oracle.get("task_completed"),
                "violated": oracle.get("violated"),
                "violations": oracle.get("violations"),
                "missing_required_paths": oracle.get("missing_required_paths"),
                "present_forbidden_paths": oracle.get("present_forbidden_paths"),
            },
        })

    return {
        "task": raw.get("task"),
        "case_id": raw.get("case_id"),
        "condition": raw.get("condition"),
        "attribution_policy": raw.get("attribution_policy"),
        "support_track": raw.get("support_track"),
        "counterfactual_track": raw.get("counterfactual_track"),
        "initial_action": raw.get("initial_action"),
        "initial_rationale": raw.get("initial_rationale"),
        "final_action": raw.get("final_action"),
        "replan_count": raw.get("replan_count"),
        "questions_asked": raw.get("questions_asked"),
        "human_interactions": raw.get("human_interactions"),
        "residual_gate": raw.get("residual_gate"),
        "safety_evaluation": raw.get("safety_evaluation"),
        "symbolic_safety_evaluation": raw.get("symbolic_safety_evaluation"),
        "final_memory": raw.get("final_memory"),
        "inspection_cycles": cycles,
        "runtime_steps": steps,
        "runtime_oracle": runtime.get("oracle"),
        "runtime_diff": runtime.get("diff"),
        "runtime_terminal_reason": runtime.get("terminal_reason"),
        "runtime_before_snapshot": runtime.get("before_snapshot"),
        "runtime_after_snapshot": runtime.get("after_snapshot"),
    }


def _load_case(case_id, expected_sha256):
    path = CASE_DIR / f"{case_id}.json"
    if not path.exists():
        return None, {"case_file_found": False, "path": str(path)}
    blob = path.read_bytes()
    actual = hashlib.sha256(blob).hexdigest()
    integrity = {
        "case_file_found": True,
        "path": str(path).replace("\\", "/"),
        "sha256_on_disk": actual,
        "sha256_in_run_manifest": expected_sha256,


        "matches_run": (expected_sha256 is None) or (actual == expected_sha256),
    }
    return json.loads(blob.decode("utf-8")), integrity


def export(run_dir, out_dir, min_episodes=0, include_passing=False):
    run_path = Path(run_dir)
    manifest = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))
    config = manifest.get("experiment_config", {})
    episodes = manifest["episodes"]

    if min_episodes and len(episodes) < min_episodes:
        raise SystemExit(
            f"{run_path.name} has {len(episodes)} episodes, below --min-episodes {min_episodes}"
        )

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    index = []
    classes = Counter()
    symptoms = Counter()
    by_domain = Counter()
    by_operator = Counter()
    integrity_problems = []

    not_yet_run = []
    for episode in episodes.values():


        if not _summary(episode):
            not_yet_run.append({
                "case_id": episode["spec"]["case_id"],
                "status": episode.get("status"),
            })
            continue

        reasons = _reasons(episode)
        if not reasons and not include_passing:
            continue

        spec = episode["spec"]
        case_id = spec["case_id"]
        payload = spec.get("payload") or {}
        case, integrity = _load_case(case_id, payload.get("case_sha256"))
        if case is None or not integrity.get("matches_run", True):
            integrity_problems.append({"case_id": case_id, **integrity})

        klass, detail, evidence = classify(episode, case or {})
        classes[klass] += 1
        symptoms.update(reasons)
        by_domain[payload.get("domain")] += 1
        by_operator[(case or {}).get("corruption_operator")] += 1

        target = out_path / case_id
        target.mkdir(parents=True, exist_ok=True)


        if case is not None:
            (target / "case_definition.json").write_text(
                json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

        raw = _raw(episode)
        (target / "trajectory.json").write_text(
            json.dumps(_trajectory(raw), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (target / "diagnosis.json").write_text(
            json.dumps(
                {
                    "case_id": case_id,
                    "episode_id": spec["episode_id"],
                    "arm": spec.get("condition"),
                    "trial": spec.get("trial"),
                    "run_id": manifest.get("run_id") or run_path.name,
                    "model": config.get("model"),
                    "failure_class": klass,
                    "explanation": detail,
                    "symptoms": reasons,
                    "evidence": evidence,
                    "case_background": {
                        "domain": payload.get("domain"),
                        "phase": payload.get("phase"),
                        "task": (case or {}).get("task"),
                        "memory_key": (case or {}).get("memory_key"),
                        "corruption_operator": (case or {}).get("corruption_operator"),
                        "corrupted_state": (case or {}).get("corrupted_state"),
                        "correct_state": (case or {}).get("correct_state"),
                        "ground_truth_state": (case or {}).get("ground_truth_state"),
                        "oracle_support_states": (case or {}).get("oracle_support_states"),
                        "context_memories": (case or {}).get("context_memories"),
                        "safety_invariant": ((case or {}).get("safety") or {}).get("invariant"),
                        "unsafe_action": ((case or {}).get("safety") or {}).get("unsafe_action"),
                        "difficulty": (case or {}).get("difficulty"),
                        "execution_oracle": ((case or {}).get("execution") or {}).get("oracle"),
                    },
                    "case_file_integrity": integrity,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (target / "raw_result.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (target / "episode_manifest.json").write_text(
            json.dumps(episode, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        api_metrics = ((episode.get("attempts") or [{}])[-1].get("result") or {}).get("api_metrics")
        if api_metrics:
            (target / "api_metrics.json").write_text(
                json.dumps(api_metrics, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        shared_setup = ((episode.get("attempts") or [{}])[-1].get("result") or {}).get("shared_setup")
        if shared_setup and Path(shared_setup).is_file():
            shutil.copy2(shared_setup, target / "shared_setup.json")

        summary = _summary(episode)
        index.append({
            "case_id": case_id,
            "failure_class": klass,
            "symptoms": reasons,
            "domain": payload.get("domain"),
            "memory_key": (case or {}).get("memory_key"),
            "corruption_operator": (case or {}).get("corruption_operator"),
            "runtime_status": summary.get("status"),
            "task_success": summary.get("task_success"),
            "safety_violation": summary.get("safety_violation"),
            "attribution_precision": summary.get("attribution_precision"),
            "attribution_recall": summary.get("attribution_recall"),
            "annotated_candidate_count": evidence["annotated_candidate_count"],
            "critical_state_count": evidence["critical_state_count"],
            "repair_event_count": summary.get("repair_event_count"),
            "steps": summary.get("steps"),
            "difficulty": (case or {}).get("difficulty"),
            "bundle": case_id,
        })

    index.sort(key=lambda item: (item["failure_class"], item["case_id"]))
    (out_path / "index.json").write_text(
        json.dumps(
            {
                "source_run": str(run_path).replace("\\", "/"),
                "run_status": manifest.get("status"),
                "model": config.get("model"),
                "api_profile": config.get("api_profile"),
                "fake_api": config.get("fake_api"),
                "arms": config.get("arms"),
                "trials": config.get("trials"),
                "attribution_policy": config.get("attribution_policy"),
                "total_episodes": len(episodes),
                "scored_episodes": len(episodes) - len(not_yet_run),
                "not_yet_run_episodes": len(not_yet_run),
                "not_yet_run": not_yet_run,
                "exported": len(index),
                "failure_classes": dict(classes.most_common()),
                "symptom_counts": dict(symptoms.most_common()),
                "by_domain": {str(k): v for k, v in by_domain.most_common()},
                "by_corruption_operator": {str(k): v for k, v in by_operator.most_common()},
                "case_file_integrity_problems": integrity_problems,
                "bundles": index,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    taxonomy = {
        "source_run": str(run_path).replace("\\", "/"),
        "total_episodes": len(episodes),
        "scored_episodes": len(episodes) - len(not_yet_run),
        "not_yet_run_episodes": len(not_yet_run),
        "failing_episodes": len(index),
        "failure_classes": dict(classes.most_common()),
        "cases_per_class": {
            klass: sorted(item["case_id"] for item in index if item["failure_class"] == klass)
            for klass in classes
        },
    }
    (out_path / "failure_taxonomy.json").write_text(
        json.dumps(taxonomy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"source_run      : {run_path}")
    print(f"model           : {config.get('model')}  arms={config.get('arms')}")
    print(f"total_episodes  : {len(episodes)}")
    if not_yet_run:
        print(f"not_yet_run     : {len(not_yet_run)} (run still in progress; skipped)")
    print(f"scored_episodes : {len(episodes) - len(not_yet_run)}")
    print(f"exported        : {len(index)}")
    print(f"output          : {out_path}")
    print("failure_classes :")
    for klass, count in classes.most_common():
        print(f"    {count:4d}  {klass}")
    if integrity_problems:
        print(f"case_file_integrity_problems: {len(integrity_problems)}")
    return 0


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--min-episodes",
        type=int,
        default=0,
        help="refuse to export a run smaller than this (guards against grabbing a smoke run)",
    )
    parser.add_argument("--include-passing", action="store_true")
    args = parser.parse_args(argv[1:])
    return export(args.run_dir, args.out, args.min_episodes, args.include_passing)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
