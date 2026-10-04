from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
RUN_ROOT = Path('runs/')
CROSS_WORKBOOK = ROOT / 'paper_experiments/results/shared/permission_matched_v10_all_arms_20260819.xlsx'
CROSS_AUDIT = ROOT / 'paper_experiments/results/shared/audit/PERMISSION_MATCHED_V10_ALL_ARMS_20260819_AUDIT.json'
ANNOTATION_AUDIT = ROOT / 'paper_experiments/results/shared/audit/FINAL_150_V9_ANNOTATION_AUDIT.json'
RQ5_PRIMARY = ROOT / 'paper_experiments/results/rq5/rq5_v10_matched.xlsx'
RQ5_PRIMARY_VALIDATION = ROOT / 'paper_experiments/results/rq5/RQ5_V10_MATCHED_VALIDATION.json'
RQ5_REPLICATION = ROOT / 'paper_experiments/results/rq5/rq5_v10_replication3.xlsx'
RQ5_REPLICATION_VALIDATION = ROOT / 'paper_experiments/results/rq5/RQ5_V10_REPLICATION3_VALIDATION.json'
STATEWISE = "statewise_v2_contract_corrected_typedfix"
PAPER_RQ5_ARMS = {
    STATEWISE: "StateWise",
    "memlineage_trust": "MemLineage",
    "safety_sentry": "Safety Sentry",
    "ask_or_assume": "Ask-or-Assume",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sheet_rows(path: Path, sheet_name: str) -> list[dict[str, Any]]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    rows = workbook[sheet_name].iter_rows(values_only=True)
    headers = next(rows)
    return [dict(zip(headers, row)) for row in rows]


def write_csv(name: str, rows: list[dict[str, Any]]) -> None:
    fields = list(rows[0]) if rows else []
    with (OUT / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def percentile(values: Iterable[float], quantile: float) -> float | None:
    ordered = sorted(float(value) for value in values if value is not None)
    if not ordered:
        return None
    position = (len(ordered) - 1) * quantile
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def episode_key(case_id: str, arm: str, trial: int) -> tuple[str, str, int]:
    return case_id, arm, int(trial)


def compact_manifest(run_id: str, wanted: set[tuple[str, str, int]]) -> dict[tuple[str, str, int], dict[str, Any]]:
    payload = read_json(RUN_ROOT / run_id / "manifest.json")
    episodes = payload["episodes"]
    if isinstance(episodes, dict):
        episodes = episodes.values()
    compact = {}
    for episode in episodes:
        spec = episode["spec"]
        key = episode_key(spec["case_id"], spec["condition"], spec.get("trial", 0))
        if key not in wanted:
            continue
        attempts = episode.get("attempts", [])
        successful = [item for item in attempts if item.get("status") == "SUCCEEDED"]
        attempt = successful[-1] if successful else attempts[-1]
        result = attempt.get("result") or {}
        compact[key] = {
            "episode_status": episode.get("status"),
            "summary": result.get("summary") or {},
            "raw": result.get("raw_result") or {},
        }
    return compact


def attach_runtime(cross_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    wanted_by_run: dict[str, set[tuple[str, str, int]]] = defaultdict(set)
    for row in cross_rows:
        wanted_by_run[str(row["run_id"])].add(episode_key(row["case_id"], row["arm"], row["trial"]))
    indexed = {}
    hashes = {}
    for run_id, wanted in sorted(wanted_by_run.items()):
        path = RUN_ROOT / run_id / "manifest.json"
        hashes[run_id] = sha256(path)
        for key, value in compact_manifest(run_id, wanted).items():
            indexed[(run_id, *key)] = value
    enriched, missing = [], []
    for row in cross_rows:
        lookup = (str(row["run_id"]), row["case_id"], row["arm"], int(row["trial"]))
        runtime = indexed.get(lookup)
        if runtime is None:
            missing.append(lookup)
            continue
        summary, raw = runtime["summary"], runtime["raw"]
        enriched.append({
            **row,
            "questions": int(summary.get("questions") or len(raw.get("questions_asked") or [])),
            "human_interactions": int(summary.get("human_interactions") or len(raw.get("human_interactions") or [])),
            "permission_interactions": int(summary.get("permission_interactions") or len(raw.get("permission_interactions") or [])),
            "raw": raw,
            "runtime_summary": summary,
        })
    if missing:
        raise RuntimeError(f"Missing {len(missing)} runtime records; first={missing[0]}")
    return enriched, hashes


def funnel_analysis(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    cases = []
    routing_methods: Counter[str] = Counter()
    resolution_decisions = resolution_successes = 0
    for row in rows:
        if row["arm"] != STATEWISE:
            continue
        raw, summary = row["raw"], row["runtime_summary"]
        final_attr = ((raw.get("attribution_metrics") or {}).get('final') or {})
        routing = raw.get("routing_decisions") or []
        human_interactions = raw.get("human_interactions") or []
        for decision in routing:
            routing_methods[str(decision.get("method") or "UNKNOWN")] += 1
        invoked = [decision for decision in routing if decision.get("method") != "CONTINUE"]
        resolved = []
        for decision in invoked:
            state_id, state_key = decision.get("state_id"), decision.get("key")
            later_reliable = any(
                candidate.get("method") == "CONTINUE"
                and candidate.get("evidence_reliable") is True
                and (candidate.get("state_id") == state_id or candidate.get("key") == state_key)
                for candidate in routing
            )
            human_answer = any(
                interaction.get("state_key") == state_key
                and (interaction.get("answer") or {}).get("known") is True
                for interaction in human_interactions
            )
            if (
                decision.get("machine_resolved") is True
                or decision.get("human_resolved") is True
                or decision.get("evidence_reliable") is True
                or later_reliable
                or human_answer
            ):
                resolved.append(decision)
        resolution_decisions += len(invoked)
        resolution_successes += len(resolved)
        attr_evaluable = row.get("attribution_final_recall") is not None
        cases.append({
            "case_id": row["case_id"],
            "domain": row["domain"],
            "attribution_evaluable": attr_evaluable,
            "attribution_full_recall": attr_evaluable and float(row["attribution_final_recall"]) == 1.0,
            "attributed_memory_count": len(final_attr.get("memory_ids") or []),
            "critical_state_count": len(raw.get("critical_states") or []),
            "resolution_invoked": bool(invoked),
            "resolution_decision_count": len(invoked),
            "resolution_success": bool(invoked) and len(resolved) == len(invoked),
            "resolution_success_count": len(resolved),
            "questions": row["questions"],
            "repair_performed": bool(row["repair_performed"]),
            "repair_event_count": int(row["repair_event_count"] or 0),
            "repair_correct": bool(row["repair_correct"]),
            "repair_correct_event_count": int(row["repair_correct_event_count"] or 0),
            "objective_correct": bool(row["behaviorally_correct"]),
            "action_completed": bool(row["action_completed"]),
            "safety_violation": bool(row["safety_violation"]),
        })
    n = len(cases)
    attr_n = sum(item["attribution_evaluable"] for item in cases)
    attr_ok = sum(item["attribution_full_recall"] for item in cases)
    resolution_n = sum(item["resolution_invoked"] for item in cases)
    resolution_ok = sum(item["resolution_success"] for item in cases)
    repair_events = sum(item["repair_event_count"] for item in cases)
    repair_ok = sum(item["repair_correct_event_count"] for item in cases)
    funnel = [
        {"stage": "All final-protocol StateWise cases", "unit": "episode", "count": n, "denominator": n, "rate": 1.0},
        {"stage": "Attribution evaluable", "unit": "episode", "count": attr_n, "denominator": n, "rate": rate(attr_n, n)},
        {"stage": "Attribution full recall", "unit": "episode", "count": attr_ok, "denominator": attr_n, "rate": rate(attr_ok, attr_n)},
        {"stage": "Resolution invoked", "unit": "episode", "count": resolution_n, "denominator": n, "rate": rate(resolution_n, n)},
        {"stage": "Resolution successful", "unit": "episode", "count": resolution_ok, "denominator": resolution_n, "rate": rate(resolution_ok, resolution_n)},
        {"stage": "Persistent repair performed", "unit": "episode", "count": sum(item["repair_performed"] for item in cases), "denominator": n, "rate": rate(sum(item["repair_performed"] for item in cases), n)},
        {"stage": "Repair event correct", "unit": "repair_event", "count": repair_ok, "denominator": repair_events, "rate": rate(repair_ok, repair_events)},
        {"stage": "Final objective correct", "unit": "episode", "count": sum(item["objective_correct"] for item in cases), "denominator": n, "rate": rate(sum(item["objective_correct"] for item in cases), n)},
    ]
    diagnostics = {
        "routing_method_counts": dict(sorted(routing_methods.items())),
        "resolution_decisions": resolution_decisions,
        "resolution_successes": resolution_successes,
        "definition_note": "Resolution is invoked for non-CONTINUE routing decisions. Success requires an explicit resolved/reliable flag, a known human answer for the same state, or a subsequent reliable CONTINUE route for that state; episode success requires every invoked decision to resolve.",
    }
    return cases, funnel, diagnostics


def interaction_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["arm"]].append(row)
    output = []
    for arm, items in sorted(grouped.items()):
        questions = [int(item["questions"]) for item in items]
        output.append({
            "arm": arm,
            "episodes": len(items),
            "total_questions": sum(questions),
            "episodes_with_question": sum(value > 0 for value in questions),
            "question_episode_rate": rate(sum(value > 0 for value in questions), len(items)),
            "mean_questions_per_episode": statistics.fmean(questions),
            "max_questions_per_episode": max(questions),
            "total_human_interactions": sum(int(item["human_interactions"]) for item in items),
            "total_permission_interactions": sum(int(item["permission_interactions"]) for item in items),
        })
    return output


def resource_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["arm"]].append(row)
    output = []
    for arm, items in sorted(grouped.items()):
        tokens = [float(item["total_tokens"]) for item in items]
        latency = [float(item["api_latency_seconds"]) for item in items]
        calls = [float(item["api_calls"]) for item in items]
        output.append({
            "arm": arm, "episodes": len(items),
            "mean_total_tokens": statistics.fmean(tokens), "median_total_tokens": percentile(tokens, 0.5), "p95_total_tokens": percentile(tokens, 0.95),
            "mean_api_latency_seconds": statistics.fmean(latency), "median_api_latency_seconds": percentile(latency, 0.5), "p95_api_latency_seconds": percentile(latency, 0.95),
            "mean_api_calls": statistics.fmean(calls), "median_api_calls": percentile(calls, 0.5), "p95_api_calls": percentile(calls, 0.95),
        })
    return output


def failure_breakdowns(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    annotation = read_json(ANNOTATION_AUDIT)
    case_meta = {item["case_id"]: item for item in annotation["rows"]}
    grouped = defaultdict(list)
    statewise_failures = []
    for row in rows:
        meta = case_meta[row["case_id"]]
        grouped[(row["arm"], row["domain"], meta["operator"])].append(row)
        if row["arm"] == STATEWISE and not bool(row["behaviorally_correct"]):
            statewise_failures.append({
                "case_id": row["case_id"], "domain": row["domain"], "operator": meta["operator"],
                "expected_behavior": row["expected_behavior"], "action_completed": bool(row["action_completed"]),
                "correct_safe_stop": bool(row["correct_safe_stop"]), "safety_violation": bool(row["safety_violation"]),
                "failure_category": row["failure_category"] or "behavioral_objective_error", "initial_action": row["initial_action"], "final_action": row["final_action"],
            })
    output = []
    for (arm, domain, operator), items in sorted(grouped.items()):
        should_act = [item for item in items if item["expected_behavior"] == "SHOULD_ACT"]
        should_stop = [item for item in items if item["expected_behavior"] == "SHOULD_STOP"]
        failures = sum(not bool(item["behaviorally_correct"]) for item in items)
        completion_failures = sum(not bool(item["action_completed"]) for item in should_act)
        safe_stop_failures = sum(not bool(item["correct_safe_stop"]) for item in should_stop)
        violations = sum(bool(item["safety_violation"]) for item in items)
        output.append({
            "arm": arm, "domain": domain, "operator": operator, "episodes": len(items),
            "objective_failures": failures, "objective_failure_rate": rate(failures, len(items)),
            "should_act_n": len(should_act), "completion_failures": completion_failures, "completion_failure_rate": rate(completion_failures, len(should_act)),
            "should_stop_n": len(should_stop), "safe_stop_failures": safe_stop_failures, "safe_stop_failure_rate": rate(safe_stop_failures, len(should_stop)),
            "safety_violations": violations, "safety_violation_rate": rate(violations, len(items)),
        })
    return output, statewise_failures


def rq5_t1_t4(path: Path, source: str) -> list[dict[str, Any]]:
    rows = [row for row in sheet_rows(path, "Task_Data") if row["arm"] in PAPER_RQ5_ARMS]
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["arm"], int(row["task_index"]))].append(row)
    output = []
    for (arm, task_index), items in sorted(grouped.items()):
        successes = sum(bool(item["task_success"]) for item in items)
        safe_successes = sum(bool(item["risk_adjusted_task_success"]) for item in items)
        violations = sum(bool(item["safety_violation"]) for item in items)
        repairs = sum(bool(item["repair_performed"]) for item in items)
        correct_repairs = sum(bool(item["repair_correct"]) for item in items)
        output.append({
            "source": source, "method": PAPER_RQ5_ARMS[arm], "arm": arm, "task": f"T{task_index}", "episodes": len(items),
            "task_successes": successes, "task_success_rate": rate(successes, len(items)),
            "safe_successes": safe_successes, "safe_success_rate": rate(safe_successes, len(items)),
            "safety_violations": violations, "safety_violation_rate": rate(violations, len(items)),
            "repair_performed": repairs, "repair_correct": correct_repairs, "repair_accuracy": rate(correct_repairs, repairs),
            "state_reuse": sum(bool(item["state_reuse"]) for item in items),
        })
    return output


def rq5_questions(path: Path, source: str) -> list[dict[str, Any]]:
    rows = [row for row in sheet_rows(path, "Sequence_Data") if row["arm"] in PAPER_RQ5_ARMS]
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["arm"]].append(row)
    output = []
    for arm, items in sorted(grouped.items()):
        questions = [int(item["cumulative_questions"] or 0) for item in items]
        output.append({
            "source": source, "method": PAPER_RQ5_ARMS[arm], "arm": arm, "sequences": len(items), "tasks": len(items) * 4,
            "total_questions": sum(questions), "sequences_with_question": sum(value > 0 for value in questions),
            "question_sequence_rate": rate(sum(value > 0 for value in questions), len(items)),
            "questions_per_sequence": statistics.fmean(questions), "questions_per_task": sum(questions) / (len(items) * 4),
            "max_questions_per_sequence": max(questions),
        })
    return output


def rq5_resource(path: Path, source: str) -> list[dict[str, Any]]:
    sheet = "Paper_Comparison" if source == "primary" else "Replication_Summary"
    labels = {value: key for key, value in PAPER_RQ5_ARMS.items()}
    output = []
    for row in sheet_rows(path, sheet):
        arm = row.get("arm") or labels.get(row.get("method"))
        if arm not in PAPER_RQ5_ARMS:
            continue
        output.append({
            "source": source, "method": PAPER_RQ5_ARMS[arm], "arm": arm,
            "sequences": row["sequences"], "tasks": row["tasks"], "api_calls_per_task": row["api_calls_per_task"],
            "tokens_per_task": row["tokens_per_task"], "api_latency_seconds_per_task": row["api_latency_seconds_per_task"],
        })
    return output


def markdown_report(funnel: list[dict[str, Any]], questions: list[dict[str, Any]], statewise_failures: list[dict[str, Any]], validation: dict[str, Any]) -> str:
    def pct(value: Any) -> str:
        return "N/A" if value is None else f"{100 * float(value):.1f}%"
    lines = [
        "# Phase 1 Zero-Cost Analysis", "",
        "This directory is derived entirely from frozen workbooks and existing run manifests. No model/API calls were made.", "",
        "## Attribution / Resolution / Repair Funnel", "",
        "| Stage | Unit | Count | Denominator | Rate |", "|---|---:|---:|---:|---:|",
    ]
    for row in funnel:
        lines.append(f"| {row['stage']} | {row['unit']} | {row['count']} | {row['denominator']} | {pct(row['rate'])} |")
    lines += ["", "Attribution denominators include only evaluator-declared evaluable episodes. Resolution is derived from raw routing decisions; repair accuracy is event-level.", "", "## Cross-Sectional User Questions", "", "| Arm | Episodes | Questions | Episodes with question | Rate |", "|---|---:|---:|---:|---:|"]
    for row in questions:
        lines.append(f"| {row['arm']} | {row['episodes']} | {row['total_questions']} | {row['episodes_with_question']} | {pct(row['question_episode_rate'])} |")
    lines += [
        "", "## RQ5 T1-T4", "",
        "The detailed primary and replication task-level tables are in `rq5_t1_t4.csv`. Question and resource summaries remain separated by run.", "",
        "## Failure Breakdown", "", f"Final StateWise has {len(statewise_failures)} objective-error cases. See `statewise_failure_cases.csv` and `domain_operator_failure_breakdown.csv`.", "",
        "## Validation", "",
    ]
    for key, value in validation["checks"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines += [
        "", "## Interpretation Limits", "",
        "- Cross-sectional outputs inherit the final permission-matched v10 assembly: 20 matched v10 cases replace their v9 counterparts; the other 130 retain audited v9 measurements.",
        "- RQ5 primary and replication are not pooled.",
        "- The funnel is observational mechanism evidence and does not replace controlled RQ4 ablations.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    cross_rows = sheet_rows(CROSS_WORKBOOK, "Combined_Episodes")
    enriched, manifest_hashes = attach_runtime(cross_rows)
    funnel_cases, funnel, funnel_diagnostics = funnel_analysis(enriched)
    cross_questions = interaction_summaries(enriched)
    cross_resources = resource_summary(cross_rows)
    breakdown, statewise_failures = failure_breakdowns(cross_rows)
    rq5_tasks = rq5_t1_t4(RQ5_PRIMARY, "primary") + rq5_t1_t4(RQ5_REPLICATION, "replication")
    rq5_question_rows = rq5_questions(RQ5_PRIMARY, "primary") + rq5_questions(RQ5_REPLICATION, "replication")
    rq5_resource_rows = rq5_resource(RQ5_PRIMARY, "primary") + rq5_resource(RQ5_REPLICATION, "replication")

    outputs = {
        "statewise_funnel_cases.csv": funnel_cases,
        "attribution_resolution_repair_funnel.csv": funnel,
        "cross_sectional_user_questions.csv": cross_questions,
        "cross_sectional_resource_distribution.csv": cross_resources,
        "domain_operator_failure_breakdown.csv": breakdown,
        "statewise_failure_cases.csv": statewise_failures,
        "rq5_t1_t4.csv": rq5_tasks,
        "rq5_user_questions.csv": rq5_question_rows,
        "rq5_resource_summary.csv": rq5_resource_rows,
    }
    for name, rows in outputs.items():
        write_csv(name, rows)

    arms = {row["arm"] for row in cross_rows}
    cross_case_sets = {arm: {row["case_id"] for row in cross_rows if row["arm"] == arm} for arm in arms}
    annotation = read_json(ANNOTATION_AUDIT)
    expected_cases = {row["case_id"] for row in annotation["rows"]}
    checks = {
        "cross_rows_1500": len(cross_rows) == 1500,
        "cross_10_arms": len(arms) == 10,
        "identical_150_case_set_per_arm": all(cases == expected_cases for cases in cross_case_sets.values()),
        "runtime_records_attached_1500": len(enriched) == 1500,
        "statewise_funnel_cases_150": len(funnel_cases) == 150,
        "rq5_primary_validation_valid": read_json(RQ5_PRIMARY_VALIDATION).get("status") == "VALID",
        "rq5_replication_validation_valid": read_json(RQ5_REPLICATION_VALIDATION).get("status") == "VALID",
        "rq5_primary_t1_t4_cells_16": sum(row["source"] == "primary" for row in rq5_tasks) == 16,
        "rq5_replication_t1_t4_cells_16": sum(row["source"] == "replication" for row in rq5_tasks) == 16,
        "all_rq5_cells_n32": all(row["episodes"] == 32 for row in rq5_tasks),
        "cross_audit_valid": read_json(CROSS_AUDIT).get("status") == "VALID",
        "annotation_case_hashes_match": annotation.get("all_case_hashes_match") is True,
        "unique_statewise_funnel_case_ids": len({row["case_id"] for row in funnel_cases}) == len(funnel_cases),
        "unique_domain_operator_arm_rows": len({(row["arm"], row["domain"], row["operator"]) for row in breakdown}) == len(breakdown),
        "unique_rq5_source_arm_task_rows": len({(row["source"], row["arm"], row["task"]) for row in rq5_tasks}) == len(rq5_tasks),
        "statewise_objective_correct_143": sum(row["objective_correct"] for row in funnel_cases) == 143,
        "conditional_failure_rates_only_blank_at_zero_denominator": all(
            (row["completion_failure_rate"] is None) == (row["should_act_n"] == 0)
            and (row["safe_stop_failure_rate"] is None) == (row["should_stop_n"] == 0)
            for row in breakdown
        ),
        "rq5_repair_accuracy_only_blank_without_repairs": all(
            (row["repair_accuracy"] is None) == (row["repair_performed"] == 0)
            for row in rq5_tasks
        ),
        "nonconditional_outputs_complete": all(
            value is not None
            for rows in (funnel, cross_questions, cross_resources, rq5_question_rows, rq5_resource_rows, statewise_failures, funnel_cases)
            for row in rows
            for value in row.values()
        ),
    }
    source_paths = (CROSS_WORKBOOK, CROSS_AUDIT, ANNOTATION_AUDIT, RQ5_PRIMARY, RQ5_PRIMARY_VALIDATION, RQ5_REPLICATION, RQ5_REPLICATION_VALIDATION)
    validation = {
        "status": "VALID" if all(checks.values()) else "INVALID", "offline_only": True, "checks": checks,
        "funnel_diagnostics": funnel_diagnostics,
        "source_files": {str(path.relative_to(ROOT)): sha256(path) for path in source_paths},
        "source_run_manifests": manifest_hashes,
        "generated_files": [*outputs, "REPORT.md"],
    }
    (OUT / "validation.json").write_text(json.dumps(validation, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    (OUT / "REPORT.md").write_text(markdown_report(funnel, cross_questions, statewise_failures, validation), encoding="utf-8")
    if validation["status"] != "VALID":
        raise SystemExit(json.dumps(checks, indent=2))
    print(json.dumps({"status": "VALID", "output": str(OUT), "checks": checks}, indent=2))


if __name__ == "__main__":
    main()
