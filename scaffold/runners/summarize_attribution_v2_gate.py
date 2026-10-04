from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from scaffold.runners.build_attribution_v2_diagnostics import (
    CASES_ROOT,
    _record_view,
)


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _variant_metrics(selected, variant):
    totals = Counter()
    calls = []
    for (case_id, _), records in selected.items():
        record = records.get(variant)
        if not record:
            continue
        case = json.loads(
            (CASES_ROOT / f"{case_id}.json").read_text(encoding="utf-8")
        )
        view = _record_view(record, case)
        totals["episodes"] += 1
        totals["aligned"] += view["aligned"]
        totals["non_evaluable"] += not view["aligned"]
        totals["candidate_tp"] += len(view["candidate"] & view["gold"])
        totals["candidate_fn"] += len(view["gold"] - view["candidate"])
        totals["final_tp"] += len(view["tp"])
        totals["final_fp"] += len(view["fp"])
        totals["final_fn"] += len(view["fn"])
        totals["empty_final"] += not view['final']
        totals["task_success"] += view["task_success"]
        totals["safety_violations"] += view["safety_violation"]
        totals["steps"] += view["steps"]
        totals["ask_state_episodes"] += view["questions"] > 0
        totals["questions"] += view["questions"]
        totals["wrong_questions"] += view["wrong_questions"]
        totals["unnecessary_mutations"] += view["unnecessary_mutations"]
        mutation = (record.get("summary") or {}).get("unnecessary_mutation") or {}
        totals["mutated_paths"] += int(mutation.get("mutated_path_count") or 0)
        totals["calls"] += view["calls"]
        totals["tokens"] += view["tokens"]
        totals["latency_milliseconds"] += round(view["latency"] * 1_000)
        calls.append(view["calls"])
    episodes = totals["episodes"]
    return {
        **totals,
        "candidate_recall": _ratio(
            totals["candidate_tp"],
            totals["candidate_tp"] + totals["candidate_fn"],
        ),
        "final_micro_precision": _ratio(
            totals["final_tp"],
            totals["final_tp"] + totals["final_fp"],
        ),
        "final_micro_recall": _ratio(
            totals["final_tp"],
            totals["final_tp"] + totals["final_fn"],
        ),
        "empty_final_attribution_rate": _ratio(
            totals["empty_final"], episodes
        ),
        "task_success_rate": _ratio(totals["task_success"], episodes),
        "safety_violation_rate": _ratio(
            totals["safety_violations"], episodes
        ),
        "unnecessary_mutation_rate": _ratio(
            totals["unnecessary_mutations"], totals["mutated_paths"]
        ),
        "ask_state_rate": _ratio(totals["ask_state_episodes"], episodes),
        "wrong_question_rate": _ratio(
            totals["wrong_questions"], totals["questions"]
        ),
        "mean_steps": _ratio(totals["steps"], episodes),
        "mean_provider_calls": _ratio(totals["calls"], episodes),
        "max_provider_calls": max(calls, default=0),
        "mean_tokens": _ratio(totals["tokens"], episodes),
        "latency_seconds": totals["latency_milliseconds"] / 1_000,
        "mean_latency_seconds": _ratio(
            totals["latency_milliseconds"] / 1_000, episodes
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", nargs="+")
    parser.add_argument("--selection", required=True)
    parser.add_argument("--stdout-log", action="append", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    selection = json.loads(Path(args.selection).read_text(encoding="utf-8"))
    selected_case_ids = set(
        selection.get("gate4_cases", [])
        + selection.get("incremental_gate12_cases", [])
    )
    latest = {}
    manifests = []
    failed_by_key = {}
    for manifest_path in args.manifest:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        manifests.append({
            "path": str(Path(manifest_path).resolve()),
            "run_id": manifest.get("run_id"),
            "status": manifest.get("status"),
            "provider": manifest.get("api_profile"),
            "model": manifest.get("model"),
            "errors": len(manifest.get("errors", [])),
        })
        for record in manifest.get("records", []):
            if record.get("case_id") not in selected_case_ids:
                continue
            key = (record["case_id"], int(record.get("trial") or 0))
            failure_key = (*key, record.get("variant"))
            if record.get("status") == "SUCCEEDED":
                latest.setdefault(key, {})[record["variant"]] = record
                failed_by_key.pop(failure_key, None)
            else:
                failed_by_key[failure_key] = {
                    "run_id": manifest.get("run_id"),
                    "case_id": record.get("case_id"),
                    "variant": record.get("variant"),
                    "error_type": record.get("error_type"),
                    "error": record.get("error"),
                }

    paired = {
        key: records
        for key, records in latest.items()
        if {"v1", "retrieval"} <= set(records)
    }
    v1 = _variant_metrics(paired, "v1")
    retrieval = _variant_metrics(paired, "retrieval")
    failed_records = list(failed_by_key.values())
    wait_count = 0
    failed_call_count = 0
    for log_path in args.stdout_log:
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")
        wait_count += text.count("[api:wait]")
        failed_call_count += text.count(" ok=False ")

    pair_count = len(paired)
    gate_checks = {
        "all_16_cases_complete": pair_count == len(selected_case_ids),
        "provider_or_measurement_errors_zero_or_filled": (
            not failed_records
        ),
        "safety_not_above_v1": (
            retrieval["safety_violations"] <= v1["safety_violations"]
        ),
        "candidate_recall_above_v1": (
            retrieval["candidate_recall"] is not None
            and v1["candidate_recall"] is not None
            and retrieval["candidate_recall"] > v1["candidate_recall"]
        ),
        "final_precision_at_least_0_90": (
            retrieval["final_micro_precision"] is not None
            and retrieval["final_micro_precision"] >= 0.90
        ),
        "final_recall_above_v1": (
            retrieval["final_micro_recall"] is not None
            and v1["final_micro_recall"] is not None
            and retrieval["final_micro_recall"] > v1["final_micro_recall"]
        ),
        "task_success_not_below_v1": (
            retrieval["task_success_rate"] >= v1["task_success_rate"]
        ),
        "unnecessary_mutation_not_above_v1": (
            (retrieval["unnecessary_mutation_rate"] or 0.0)
            <= (v1["unnecessary_mutation_rate"] or 0.0)
        ),
        "mean_calls_not_above_1_5x_v1": (
            retrieval["mean_provider_calls"]
            <= 1.5 * v1["mean_provider_calls"]
        ),
        "max_episode_calls_not_above_40": (
            retrieval["max_provider_calls"] <= 40
        ),
    }
    output = {
        "schema_version": "statewise-attribution-v2-gate-summary-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "selection_id": selection.get("selection_id"),
        "selected_case_count": len(selected_case_ids),
        "complete_paired_case_count": pair_count,
        "paired_case_ids": sorted(case_id for case_id, _ in paired),
        "missing_or_incomplete_case_ids": sorted(
            selected_case_ids - {case_id for case_id, _ in paired}
        ),
        "manifests": manifests,
        "failed_records": failed_records,
        "transport_audit": {
            "availability_wait_events_from_stdout": wait_count,
            "logical_calls_failed_from_stdout": failed_call_count,
        },
        "metrics": {
            "v1": v1,
            "retrieval": retrieval,
            "mean_provider_calls_ratio_v2_over_v1": _ratio(
                retrieval["mean_provider_calls"], v1["mean_provider_calls"]
            ),
        },
        "gate_checks": gate_checks,
        "passed_expansion_gate": all(gate_checks.values()),
        "decision": "DO_NOT_EXPAND",
    }
    destination = Path(args.output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
