from __future__ import annotations

import csv
import json
import math
import random
from collections import defaultdict
from pathlib import Path

import openpyxl


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
PRIMARY = REPO / 'paper_experiments/results/shared/permission_matched_v10_all_arms_20260819.xlsx'
RQ5 = REPO / 'paper_experiments/results/rq5/rq5_v10_matched.xlsx'
RQ4 = Path('runs/formal_v10_rq4_ablations150_gpt56sol_20260822_r1/pilot_summary.json')

ARM_NAMES = {
    "correct": "Correct memory",
    "corrupted": "Corrupted memory",
    "no_memory": "No memory",
    "bare_approval": "Bare approval",
    "rationale_approval": "Rationale approval",
    "generic_clarification": "Clarification",
    "memlineage_trust": "MemLineage",
    "safety_sentry": "Safety Sentry",
    "ask_or_assume": "Ask-or-Assume",
    "statewise_v2_contract_corrected_typedfix": "StateWise",
}

ARM_GROUPS = {
    "correct": "Memory",
    "corrupted": "Memory",
    "no_memory": "Memory",
    "bare_approval": "Action",
    "rationale_approval": "Action",
    "generic_clarification": "Action",
    "memlineage_trust": "Systems",
    "safety_sentry": "Systems",
    "ask_or_assume": "Systems",
    "statewise_v2_contract_corrected_typedfix": "Systems",
}

RQ4_NAMES = {
    "statewise_v2_contract_corrected_typedfix": "Full StateWise",
    "statewise_ablation_no_attribution": "w/o Attribution",
    "statewise_ablation_no_resolution": "w/o Resolution",
    "statewise_ablation_no_repair": "w/o Persistent Repair",
    "statewise_ablation_no_replan": "w/o Replanning",
    "statewise_ablation_no_residual_gate": "w/o Residual Gate",
    "statewise_ablation_no_typed_grounding": "w/o Typed Grounding",
}


def sheet_rows(path: Path, sheet: str) -> list[dict[str, object]]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    worksheet = workbook[sheet]
    rows = worksheet.iter_rows(values_only=True)
    header = list(next(rows))
    return [dict(zip(header, row)) for row in rows]


def write_csv(name: str, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"No rows for {name}")
    with (ROOT / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def rate(value: object) -> float | None:
    return None if value is None else round(float(value) * 100, 1)


def exact_mcnemar_p(full: list[bool], other: list[bool]) -> tuple[int, int, float]:
    full_only = sum(a and not b for a, b in zip(full, other))
    other_only = sum(b and not a for a, b in zip(full, other))
    discordant = full_only + other_only
    if discordant == 0:
        return full_only, other_only, 1.0
    tail = sum(math.comb(discordant, k) for k in range(min(full_only, other_only) + 1))
    p_value = min(1.0, 2 * tail / (2**discordant))
    return full_only, other_only, p_value


def paired_bootstrap_ci(full: list[bool], other: list[bool], seed: int = 20260823) -> tuple[float, float]:
    rng = random.Random(seed)
    diffs = []
    n = len(full)
    for _ in range(20_000):
        indices = [rng.randrange(n) for _ in range(n)]
        diffs.append(sum(full[i] - other[i] for i in indices) * 100 / n)
    diffs.sort()
    return diffs[int(0.025 * len(diffs))], diffs[int(0.975 * len(diffs))]


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values, key=p_values.get)
    adjusted: dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for rank, key in enumerate(ordered):
        running = max(running, min(1.0, (total - rank) * p_values[key]))
        adjusted[key] = running
    return adjusted


def build_primary() -> list[dict[str, object]]:
    summary = {row["arm"]: row for row in sheet_rows(PRIMARY, "Arm_Summary")}
    strata = defaultdict(lambda: defaultdict(list))
    for row in sheet_rows(PRIMARY, "Combined_Episodes"):
        case_id = str(row["case_id"])
        if "core_repo_state_environment_dependency" in case_id:
            stratum = "runtime"
        elif row["domain"] == "git_state":
            stratum = "git"
        else:
            stratum = "workspace"
        strata[row["arm"]][stratum].append(row)

    order = list(ARM_NAMES)
    rows = []
    for arm in order:
        source = summary[arm]
        row = {
            "group": ARM_GROUPS[arm],
            "approach": ARM_NAMES[arm],
            "objective_correctness": rate(source["behavioral_correctness_rate"]),
            "action_completion": rate(source["action_completion_rate"]),
            "safe_stop": rate(source["safe_stop_rate"]),
            "no_violation": round(100 - rate(source["safety_violation_rate"]), 1),
            "safety_violation": rate(source["safety_violation_rate"]),
            "repair_coverage": round(float(source["repair_correct_event_count"] or 0) / 150 * 100, 1),
            "repair_accuracy": rate(source["repair_accuracy_rate"]),
            "unnecessary_mutation": rate(source["mean_unnecessary_mutation_rate"]),
            "api_calls": round(float(source["mean_api_calls"]), 1),
            "tokens": round(float(source["mean_total_tokens"])),
            "latency_seconds": round(float(source["mean_api_latency_seconds"]), 1),
        }
        for stratum, label in (
            ("runtime", "runtime_objective"),
            ("workspace", "workspace_objective"),
            ("git", "git_objective"),
        ):
            items = strata[arm][stratum]
            row[label] = round(sum(bool(item["behaviorally_correct"]) for item in items) / len(items) * 100, 1)
        rows.append(row)

    write_csv("primary_claim_matrix.csv", rows)
    by_name = {row["approach"]: row for row in rows}
    write_csv("rq1_table.csv", [by_name[name] for name in ("Correct memory", "Corrupted memory", "No memory", "StateWise")])
    write_csv("rq2_table.csv", [by_name[name] for name in ("Corrupted memory", "Bare approval", "Rationale approval", "Clarification", "StateWise")])
    write_csv("rq3_table.csv", [by_name[name] for name in ("Corrupted memory", "MemLineage", "Safety Sentry", "Ask-or-Assume", "StateWise")])
    return rows


def build_rq4() -> list[dict[str, object]]:
    payload = json.loads(RQ4.read_text(encoding="utf-8"))
    summary = {row["arm"]: row for row in payload["table"]}
    records = defaultdict(dict)
    for record in payload["records"]:
        records[record["arm"]][record["case_id"]] = record
    case_ids = sorted(next(iter(records.values())))
    full_arm = "statewise_v2_contract_corrected_typedfix"

    def objective(record: dict[str, object]) -> bool:
        return bool((record["risk_adjusted_task_success"] or record["acceptable_safe_terminal"])
                    and not record["safety_violation"])

    full_values = [objective(records[full_arm][case]) for case in case_ids]
    raw_p = {}
    tests = {}
    for arm in RQ4_NAMES:
        if arm == full_arm:
            continue
        other = [objective(records[arm][case]) for case in case_ids]
        full_only, other_only, p_value = exact_mcnemar_p(full_values, other)
        ci_low, ci_high = paired_bootstrap_ci(full_values, other, seed=20260823 + len(raw_p))
        raw_p[arm] = p_value
        tests[arm] = (full_only, other_only, p_value, ci_low, ci_high)
    adjusted = holm_adjust(raw_p)

    full = summary[full_arm]
    full_obj = (full["task_success"] + full["safe_terminal"]) / 150 * 100
    full_comp = full["task_success"] / 125 * 100
    order = list(RQ4_NAMES)
    rows = []
    for arm in order:
        source = summary[arm]
        obj = (source["task_success"] + source["safe_terminal"]) / 150 * 100
        comp = source["task_success"] / 125 * 100
        row = {
            "arm": RQ4_NAMES[arm],
            "objective_correctness": round(obj, 1),
            "action_completion": round(comp, 1),
            "safe_stop": round(source["safe_terminal"] / 25 * 100, 1),
            "safety_violation": round(source["safety_violation"] / 150 * 100, 1),
            "delta_objective": round(obj - full_obj, 1),
            "delta_completion": round(comp - full_comp, 1),
            "questions": source["questions"],
            "repair_accuracy": rate(source["memory_repair_accuracy"]),
            "mean_api_calls": round(source["api_calls"] / 150, 1),
            "mean_tokens": round(source["api_total_tokens"] / 150),
            "paired_ci_low": None,
            "paired_ci_high": None,
            "mcnemar_p": None,
            "holm_p": None,
        }
        if arm != full_arm:
            _, _, p_value, ci_low, ci_high = tests[arm]
            row.update({
                "paired_ci_low": round(ci_low, 1),
                "paired_ci_high": round(ci_high, 1),
                "mcnemar_p": p_value,
                "holm_p": adjusted[arm],
            })
        rows.append(row)
    write_csv("rq4_component_matrix.csv", rows)
    return rows


def build_rq5() -> list[dict[str, object]]:
    sequence_rows = [
        row for row in sheet_rows(RQ5, "Sequence_Data")
        if row["arm"] != "arm" and row["primary_in_scope"] is True
    ]
    strict = defaultdict(list)
    for row in sequence_rows:
        strict[row["arm"]].append(
            bool(row["future_task_success_rate"] == 1 and row["future_no_violation_rate"] == 1)
        )
    sources = sheet_rows(RQ5, "Paper_Comparison")
    sources.extend(row for row in sheet_rows(RQ5, "Diagnostic_Controls") if row["arm"] == "correct")
    source_arms = {
        "StateWise": "statewise_v2_contract_corrected_typedfix",
        "MemLineage": "memlineage_trust",
        "Safety Sentry": "safety_sentry",
        "Ask-or-Assume": "ask_or_assume",
        "correct": "correct",
    }
    rows = []
    for source in sources:
        method = "Correct memory (oracle)" if source.get("arm") == "correct" else source["method"]
        arm = source_arms[source.get("method", source.get("arm"))]
        rows.append({
            "method": method,
            "all_future_safe_completion": round(sum(strict[arm]) / len(strict[arm]) * 100, 1),
            "future_completion": rate(source["future_task_success_rate"]),
            "future_no_violation": rate(source["future_no_violation_rate"]),
            "t1_repair": rate(source["t1_repair_success_rate"]),
            "state_handoff": rate(source["state_handoff_integrity_rate"]),
            "state_reuse": rate(source["state_reuse_rate"]),
            "repeated_intervention": rate(source["repeated_intervention_rate"]),
            "api_calls_per_task": round(float(source["api_calls_per_task"]), 1),
            "tokens_per_task": round(float(source["tokens_per_task"])),
            "latency_seconds_per_task": round(float(source["api_latency_seconds_per_task"]), 1),
        })
    write_csv("rq5_table.csv", rows)
    return rows


if __name__ == "__main__":
    build_primary()
    build_rq4()
    build_rq5()
    print("Wrote primary, RQ1-RQ5 claim tables from frozen artifacts.")
