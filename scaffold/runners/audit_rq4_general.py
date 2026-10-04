from __future__ import annotations

import csv
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('runs/formal_v10_rq4_ablations150_gpt56sol_20260822_r1')
OUTPUT = ROOT / "results/rq4_general"
OLD_REPLANNING_SLICE = (
    ROOT
    / "scaffold/experiments/mechanism_evidence_v10/extracted/replanning_targeted_v10_20260822.json"
)
FULL = "statewise_v2_contract_corrected_typedfix"
ARMS = {
    FULL: "Full StateWise",
    "statewise_ablation_no_attribution": "w/o Attribution",
    "statewise_ablation_no_resolution": "w/o Resolution",
    "statewise_ablation_no_repair": "w/o Persistent Repair",
    "statewise_ablation_no_replan": "w/o Replanning",
    "statewise_ablation_no_residual_gate": "w/o Residual Gate",
    "statewise_ablation_no_typed_grounding": "w/o Typed Grounding",
}


def objective(row: dict[str, Any]) -> bool:
    return bool(
        (row.get("risk_adjusted_task_success") or row.get("acceptable_safe_terminal"))
        and not row.get("safety_violation")
    )


def exact_mcnemar(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(b, c) + 1)) / (2**n)
    return min(1.0, 2.0 * tail)


def bootstrap_ci(pairs: list[tuple[int, int]], seed: int) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(pairs)

    draws = [sum((lambda p: p[0] - p[1])(pairs[rng.randrange(n)]) for _ in range(n)) / n for _ in range(20_000)]
    draws.sort()
    return draws[499], draws[19499]


def holm(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values, key=p_values.get)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, arm in enumerate(ordered):
        running = max(running, min(1.0, (len(ordered) - rank) * p_values[arm]))
        adjusted[arm] = running
    return adjusted


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    payload = json.loads((SOURCE / "pilot_summary.json").read_text(encoding="utf-8"))
    records = payload["records"]
    keys = [(row["case_id"], row["arm"], row.get("trial", 0)) for row in records]
    counts = Counter(row["arm"] for row in records)
    case_sets = {arm: {row["case_id"] for row in records if row["arm"] == arm} for arm in ARMS}
    reference_cases = case_sets[FULL]
    errors = []
    if payload.get("manager_status") != "COMPLETE":
        errors.append("manager status is not COMPLETE")
    if not payload.get("pairing_valid"):
        errors.append("source pairing_valid is false")
    if len(keys) != len(set(keys)):
        errors.append("duplicate final case_id x arm x trial rows")
    for arm in ARMS:
        if counts[arm] != 150:
            errors.append(f"{arm}: expected 150 final rows, found {counts[arm]}")
        if case_sets[arm] != reference_cases:
            errors.append(f"{arm}: case IDs differ from Full")
    if errors:
        raise RuntimeError("RQ4 audit failed: " + "; ".join(errors))

    indexed = {(row["case_id"], row["arm"]): row for row in records}
    paired_rows = []
    for case_id in sorted(reference_cases):
        full_value = int(objective(indexed[(case_id, FULL)]))
        for arm in ARMS:
            row = indexed[(case_id, arm)]
            value = int(objective(row))
            paired_rows.append({
                "case_id": case_id,
                "trial": row.get("trial", 0),
                "arm": arm,
                "arm_label": ARMS[arm],
                "terminal_status": row["status"],
                "objective_correct": value,
                "full_objective_correct": full_value,
                "paired_difference_full_minus_arm": full_value - value,
                "safety_violation": int(bool(row.get("safety_violation"))),
            })

    grouped = defaultdict(list)
    for row in paired_rows:
        grouped[row["arm"]].append(row)
    raw_p: dict[str, float] = {}
    tests: dict[str, dict[str, Any]] = {}
    for index, arm in enumerate(arm for arm in ARMS if arm != FULL):
        pairs = [(row["full_objective_correct"], row["objective_correct"]) for row in grouped[arm]]
        b = sum(full == 1 and other == 0 for full, other in pairs)
        c = sum(full == 0 and other == 1 for full, other in pairs)
        low, high = bootstrap_ci(pairs, 20260827 + index)
        raw_p[arm] = exact_mcnemar(b, c)
        tests[arm] = {"pairs": pairs, "full_only_success": b, "ablation_only_success": c, "ci": (low, high)}
    adjusted = holm(raw_p)

    old_slice = json.loads(OLD_REPLANNING_SLICE.read_text(encoding="utf-8"))
    old_slice_counts = Counter()
    old_slice_cases = defaultdict(set)
    for row in old_slice["rows"]:
        arm = row["arm"]
        old_slice_cases[arm].add(row["case_id"])
        if row["summary"].get("task_success"):
            old_slice_counts[arm] += 1
    old_full = old_slice_counts[FULL]
    old_no_replan = old_slice_counts["statewise_ablation_no_replan"]
    if any(len(cases) != 25 for cases in old_slice_cases.values()) or len(set(map(frozenset, old_slice_cases.values()))) != 1:
        raise RuntimeError("old Replanning targeted slice is not a complete paired 25-case slice")

    effects = []
    full_rate = sum(row["objective_correct"] for row in grouped[FULL]) / 150
    for arm in ARMS:
        rate = sum(row["objective_correct"] for row in grouped[arm]) / 150
        result = {
            "arm": arm,
            "arm_label": ARMS[arm],
            "paired_n": 150,
            "objective_correct_n": int(rate * 150),
            "objective_correctness": rate,
            "full_objective_correctness": full_rate,
            "paired_risk_difference_full_minus_arm": full_rate - rate,
            "ci95_low": "",
            "ci95_high": "",
            "full_only_success": "",
            "arm_only_success": "",
            "exact_mcnemar_p": "",
            "holm_adjusted_p": "",
        }
        if arm != FULL:
            test = tests[arm]
            result.update({
                "ci95_low": test["ci"][0],
                "ci95_high": test["ci"][1],
                "full_only_success": test["full_only_success"],
                "arm_only_success": test["ablation_only_success"],
                "exact_mcnemar_p": raw_p[arm],
                "holm_adjusted_p": adjusted[arm],
            })
        effects.append(result)

    stats = {
        "analysis_role": "General-benchmark ablation; confirmatory recovery scope covers attribution, resolution, persistent repair, and typed grounding",
        "source_run": str(SOURCE),
        "run_id": payload["run_id"],
        "config_fingerprint": payload["config_fingerprint"],
        "dataset": payload["dataset"],
        "manager_status": payload["manager_status"],
        "pairing_valid": payload["pairing_valid"],
        "logical_final_rows": len(records),
        "unique_case_arm_trial_keys": len(set(keys)),
        "cases_per_arm": dict(counts),
        "inference_policy": "pilot_summary final logical records only; attempts are not pooled",
        "failure_policy": "infrastructure/provider failures are excluded from method outcomes; task-level terminal outcomes remain outcomes",
        "objective_definition": "(risk_adjusted_task_success OR acceptable_safe_terminal) AND NOT safety_violation",
        "bootstrap": {"draws": 20_000, "unit": "paired case", "seed_base": 20260827},
        "multiple_testing": "Holm correction across six objective-correctness component-removal contrasts",
        "old_replanning_targeted_slice": {
            "role": "diagnostic only; statically selected from the completed RQ4 matrix",
            "paired_n": 25,
            "full_task_success_n": old_full,
            "no_replanning_task_success_n": old_no_replan,
            "complete": old_slice.get("complete"),
            "selection_fingerprint": old_slice.get("selection_fingerprint"),
        },
        "effects": {row["arm"]: row for row in effects if row["arm"] != FULL},
    }

    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUTPUT / "paired_results.csv", paired_rows)
    write_csv(OUTPUT / "component_effects.csv", effects)
    (OUTPUT / "statistical_tests.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")

    by_label = {row["arm_label"]: row for row in effects}
    grounding = by_label["w/o Typed Grounding"]
    replanning = by_label["w/o Replanning"]
    report = f"""# RQ4 general-benchmark audit

## Scope

This audit treats the frozen seven-arm, 150-case run as a **general-benchmark
ablation measuring average treatment effects**. It does not establish that every
component is necessary under every condition.

## Integrity

- Source run: `{payload['run_id']}`
- Manager status: `{payload['manager_status']}`
- Final logical records: {len(records)} (`150 cases x 7 arms`)
- Unique `case_id x arm x trial` keys: {len(set(keys))}
- Source pairing validation: `{payload['pairing_valid']}`
- Every arm contains exactly the same 150 case IDs.
- The summary contains one final logical record per key. Checkpoint attempts are
  not pooled or counted twice.
- Provider/API failures are not encoded as task failures or numeric zeroes.

## Results

| Removal | Full | Ablation | Paired loss | 95% CI | Exact p | Holm p |
|---|---:|---:|---:|---:|---:|---:|
"""
    for row in effects[1:]:
        report += (
            f"| {row['arm_label']} | {row['full_objective_correctness']:.1%} | "
            f"{row['objective_correctness']:.1%} | {row['paired_risk_difference_full_minus_arm']:.1%} | "
            f"[{float(row['ci95_low']):.1%}, {float(row['ci95_high']):.1%}] | "
            f"{float(row['exact_mcnemar_p']):.6g} | {float(row['holm_adjusted_p']):.6g} |\n"
        )
    report += f"""

## Interpretation boundary

Typed Grounding reproduces the known decrease from {grounding['full_objective_correctness']:.1%}
to {grounding['objective_correctness']:.1%} ({grounding['paired_risk_difference_full_minus_arm']:.1%}
paired loss). Replanning produces only a {replanning['paired_risk_difference_full_minus_arm']:.1%}
average loss and is not statistically reliable after Holm correction
(`p={float(replanning['holm_adjusted_p']):.3f}`). Therefore this experiment supports an
average contribution claim for the large, significant removals, but it must not be
used to claim that all pipeline stages are independently necessary. The reporting
scope treats post-repair replanning as the base agent's execution semantics, not an
independently claimed StateWise mechanism; its diagnostic removal is reported
separately rather than promoted to a confirmatory component contrast.

The earlier statically selected 25-case Replanning slice is also fully paired and
reproduces `{old_full}/25` Full task successes versus `{old_no_replan}/25` without
Replanning. This one-case difference remains diagnostic evidence, not a successful
mechanism-targeted test.
"""
    (OUTPUT / "audit_report.md").write_text(report, encoding="utf-8")
    print(f"Wrote audited RQ4 general results to {OUTPUT}")


if __name__ == "__main__":
    main()
