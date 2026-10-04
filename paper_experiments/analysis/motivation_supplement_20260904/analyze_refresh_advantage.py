from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import binomtest


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PER_EPISODE = OUT / "per_episode.csv"
CASES = Path('scaffold\\experiments\\w1_contract_corrected_v2\\cases')
FORMAL = Path('runs/mostly-correct-formal150-api_02-gpt56sol-20260903-r1')
REFRESH = Path('runs/mostly-correct-refresh-fixed150-api_02-gpt56sol-20260903-r1')
RECOVERY = Path('runs/mostly-correct-refresh-fixed-recovery4-api_02-gpt56sol-20260904-r1')
SEED = 20260904


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def as_bool(value) -> bool:
    return str(value).strip().lower() == "true"


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def wilson(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return math.nan, math.nan
    p = successes / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return 100 * (center - radius), 100 * (center + radius)


def paired_bootstrap(a: np.ndarray, b: np.ndarray, salt: int) -> tuple[float, float]:
    delta = a.astype(float) - b.astype(float)
    rng = np.random.default_rng(SEED + salt)
    samples = rng.choice(delta, size=(100_000, len(delta)), replace=True).mean(axis=1)
    low, high = np.quantile(samples, [0.025, 0.975])
    return 100 * float(low), 100 * float(high)


def holm_adjust(p_values: list[float]) -> list[float]:
    order = sorted(range(len(p_values)), key=p_values.__getitem__)
    adjusted = [1.0] * len(p_values)
    running = 0.0
    m = len(p_values)
    for rank, index in enumerate(order):
        candidate = min(1.0, (m - rank) * p_values[index])
        running = max(running, candidate)
        adjusted[index] = running
    return adjusted


def main() -> int:
    cases = {}
    for path in CASES.glob("*.json"):
        case = read_json(path)
        cases[case["case_id"]] = case
    assert len(cases) == 150

    with PER_EPISODE.open(newline="", encoding="utf-8-sig") as handle:
        compact = list(csv.DictReader(handle))
    index = {(row["case_id"], row["arm"]): row for row in compact}

    formal = read_json(FORMAL / "pilot_summary.json")["records"]
    refresh = read_json(REFRESH / "pilot_summary.json")["records"]
    recovery = read_json(RECOVERY / "pilot_summary.json")["records"]
    sw_detail = {
        row["case_id"]: row for row in formal
        if row["arm"] == "statewise_v2_contract_corrected_typedfix"
    }
    rf_detail = {
        row["case_id"]: row for row in refresh
        if row["arm"] == "live_refresh"
    }
    rf_detail.update({
        row["case_id"]: row for row in recovery
        if row["arm"] == "live_refresh"
    })
    assert len(sw_detail) == len(rf_detail) == 150

    def memberships(case: dict) -> dict[str, bool]:
        return {
            "git_state": case["domain"] == "git_state",
            "scope_mismatch": case["corruption_operator"] == "SCOPE_MISMATCH",
            "stale_value": case["corruption_operator"] == "STALE_VALUE",
        }

    case_ids = sorted(cases)
    focus = {
        "all_cases": case_ids,
        "git_state": [case_id for case_id in case_ids if memberships(cases[case_id])["git_state"]],
        "scope_mismatch": [case_id for case_id in case_ids if memberships(cases[case_id])["scope_mismatch"]],
        "stale_value": [case_id for case_id in case_ids if memberships(cases[case_id])["stale_value"]],
    }
    focus_union = set(focus["git_state"]) | set(focus["scope_mismatch"]) | set(focus["stale_value"])
    focus["focus_union"] = sorted(focus_union)
    focus["none_of_three"] = sorted(set(case_ids) - focus_union)

    strata_rows = []
    raw_focus_p = []
    raw_focus_indices = []
    for salt, (name, ids) in enumerate(focus.items()):
        sw_rows = [index[(case_id, "statewise_corrupted")] for case_id in ids]
        rf_rows = [index[(case_id, "refresh_corrupted")] for case_id in ids]
        sw = np.array([as_bool(row["overall_correct"]) for row in sw_rows], dtype=bool)
        rf = np.array([as_bool(row["overall_correct"]) for row in rf_rows], dtype=bool)
        both_correct = int(np.sum(sw & rf))
        sw_only = int(np.sum(sw & ~rf))
        rf_only = int(np.sum(~sw & rf))
        both_fail = int(np.sum(~sw & ~rf))
        discordant = sw_only + rf_only
        exact_p = float(binomtest(min(sw_only, rf_only), discordant, 0.5).pvalue) if discordant else 1.0
        sw_ci = wilson(int(sw.sum()), len(ids))
        rf_ci = wilson(int(rf.sum()), len(ids))
        diff_ci = paired_bootstrap(sw, rf, salt)
        should_act = [i for i, case_id in enumerate(ids) if as_bool(sw_rows[i]["should_act"])]
        row = {
            "stratum": name,
            "n": len(ids),
            "statewise_correct_n": int(sw.sum()),
            "statewise_correct_pct": 100 * float(sw.mean()),
            "statewise_wilson_low_pct": sw_ci[0],
            "statewise_wilson_high_pct": sw_ci[1],
            "refresh_correct_n": int(rf.sum()),
            "refresh_correct_pct": 100 * float(rf.mean()),
            "refresh_wilson_low_pct": rf_ci[0],
            "refresh_wilson_high_pct": rf_ci[1],
            "difference_pp": 100 * float((sw.astype(float) - rf.astype(float)).mean()),
            "paired_bootstrap_low_pp": diff_ci[0],
            "paired_bootstrap_high_pp": diff_ci[1],
            "both_correct": both_correct,
            "statewise_only": sw_only,
            "refresh_only": rf_only,
            "both_fail": both_fail,
            "mcnemar_exact_p": exact_p,
            "holm_p_focus_three": "",
            "should_act_n": len(should_act),
            "statewise_should_act_success_n": sum(as_bool(sw_rows[i]["task_success"]) for i in should_act),
            "refresh_should_act_success_n": sum(as_bool(rf_rows[i]["task_success"]) for i in should_act),
            "statewise_unsafe_n": sum(as_bool(row["unsafe"]) for row in sw_rows),
            "refresh_unsafe_n": sum(as_bool(row["unsafe"]) for row in rf_rows),
            "statewise_repair_n": sum(as_bool(row["repair"]) for row in sw_rows),
            "refresh_repair_n": sum(as_bool(row["repair"]) for row in rf_rows),
            "statewise_interactions_per_episode": sum(int(row["interactions"]) for row in sw_rows) / len(ids),
            "refresh_interactions_per_episode": sum(int(row["interactions"]) for row in rf_rows) / len(ids),
            "statewise_calls_per_episode": sum(int(row["calls"]) for row in sw_rows) / len(ids),
            "refresh_calls_per_episode": sum(int(row["calls"]) for row in rf_rows) / len(ids),
            "statewise_steps_per_episode": sum(int(row["steps"]) for row in sw_rows) / len(ids),
            "refresh_steps_per_episode": sum(int(row["steps"]) for row in rf_rows) / len(ids),
        }
        if name in {"git_state", "scope_mismatch", "stale_value"}:
            raw_focus_indices.append(len(strata_rows))
            raw_focus_p.append(exact_p)
        strata_rows.append(row)
    for index_here, adjusted in zip(raw_focus_indices, holm_adjust(raw_focus_p)):
        strata_rows[index_here]["holm_p_focus_three"] = adjusted

    discordant_rows = []
    for case_id in case_ids:
        sw = index[(case_id, "statewise_corrupted")]
        rf = index[(case_id, "refresh_corrupted")]
        sw_ok = as_bool(sw["overall_correct"])
        rf_ok = as_bool(rf["overall_correct"])
        if sw_ok == rf_ok:
            continue
        case = cases[case_id]
        member = memberships(case)
        sw_raw = sw_detail[case_id]
        rf_raw = rf_detail[case_id]
        discordant_rows.append({
            "case_id": case_id,
            "winner": "statewise" if sw_ok else "refresh",
            "domain": case["domain"],
            "operator": case["corruption_operator"],
            "git_state": member["git_state"],
            "scope_mismatch": member["scope_mismatch"],
            "stale_value": member["stale_value"],
            "should_act": sw["should_act"],
            "statewise_task_success": sw["task_success"],
            "refresh_task_success": rf["task_success"],
            "statewise_safe_terminal": sw["safe_terminal"],
            "refresh_safe_terminal": rf["safe_terminal"],
            "statewise_unsafe": sw["unsafe"],
            "refresh_unsafe": rf["unsafe"],
            "statewise_terminal_reason": sw_raw.get("terminal_reason", ""),
            "refresh_terminal_reason": rf_raw.get("terminal_reason", ""),
            "statewise_initial_action": json.dumps(sw_raw.get("initial_action"), ensure_ascii=False),
            "statewise_final_action": json.dumps(sw_raw.get("final_action"), ensure_ascii=False),
            "refresh_initial_action": json.dumps(rf_raw.get("initial_action"), ensure_ascii=False),
            "refresh_final_action": json.dumps(rf_raw.get("final_action"), ensure_ascii=False),
            "statewise_calls": sw["calls"],
            "refresh_calls": rf["calls"],
            "statewise_steps": sw["steps"],
            "refresh_steps": rf["steps"],
            "case_fixture": str((CASES / f"{case_id}.json").resolve()),
            "statewise_episode_id": sw_raw.get("episode_id", ""),
            "refresh_episode_id": rf_raw.get("episode_id", ""),
        })

    overlap_rows = []
    names = ("git_state", "scope_mismatch", "stale_value")
    sets = {name: set(focus[name]) for name in names}
    for left in names:
        for right in names:
            overlap_rows.append({
                "left": left,
                "right": right,
                "intersection_n": len(sets[left] & sets[right]),
            })
    patterns = {}
    for case_id in case_ids:
        member = memberships(cases[case_id])
        pattern = "+".join(name for name in names if member[name]) or "none"
        patterns.setdefault(pattern, []).append(case_id)
    pattern_rows = [{"membership_pattern": name, "n": len(ids)} for name, ids in sorted(patterns.items())]

    write_csv(OUT / "focus_strata_paired.csv", strata_rows)
    write_csv(OUT / "focus_discordant_cases.csv", discordant_rows)
    write_csv(OUT / "focus_overlap_matrix.csv", overlap_rows)
    write_csv(OUT / "focus_membership_patterns.csv", pattern_rows)

    row_by_name = {row["stratum"]: row for row in strata_rows}
    lines = [
        "# Detailed B Analysis: StateWise vs. Live Refresh",
        "",
        "This is a paired, case-level secondary analysis of the frozen 150-case corrupted-state run. "
        "Git state is a domain; scope mismatch and stale value are corruption operators. These strata overlap, "
        "so their counts and effects are not additive. The three subgroup tests are exploratory; Holm-adjusted "
        "p-values are supplied to make that limitation explicit.",
        "",
        "| Stratum | n | StateWise | Refresh | Difference | SW only / Refresh only | 95% paired bootstrap CI | Exact p | Holm p |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("all_cases", "git_state", "scope_mismatch", "stale_value", "focus_union", "none_of_three"):
        row = row_by_name[name]
        holm = row["holm_p_focus_three"]
        holm_text = f"{holm:.4f}" if holm != "" else "--"
        lines.append(
            f"| {name} | {row['n']} | {row['statewise_correct_n']}/{row['n']} "
            f"({row['statewise_correct_pct']:.1f}%) | {row['refresh_correct_n']}/{row['n']} "
            f"({row['refresh_correct_pct']:.1f}%) | {row['difference_pp']:+.1f} pp | "
            f"{row['statewise_only']} / {row['refresh_only']} | "
            f"[{row['paired_bootstrap_low_pp']:+.1f}, {row['paired_bootstrap_high_pp']:+.1f}] | "
            f"{row['mcnemar_exact_p']:.4f} | {holm_text} |"
        )
    sw_wins = [row for row in discordant_rows if row["winner"] == "statewise"]
    rf_wins = [row for row in discordant_rows if row["winner"] == "refresh"]
    lines.extend([
        "",
        "## Discordant pairs",
        "",
        f"Across all cases, StateWise alone was correct in {len(sw_wins)} cases and Refresh alone in {len(rf_wins)}. "
        "The exact case list, terminal reasons, initial/final actions, call counts, step counts, and evidence paths "
        "are in `focus_discordant_cases.csv`.",
        "",
        "## Supporting files",
        "",
        "- `focus_strata_paired.csv`: outcomes, Wilson intervals, paired bootstrap intervals, exact and adjusted tests, costs.",
        "- `focus_discordant_cases.csv`: every outcome-changing pair with trace identifiers and fixture paths.",
        "- `focus_overlap_matrix.csv`: pairwise overlap among the three focus strata.",
        "- `focus_membership_patterns.csv`: mutually exclusive overlap patterns.",
    ])
    (OUT / "FOCUS_ANALYSIS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"strata": strata_rows, "discordant_pairs": len(discordant_rows)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
