from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import binomtest


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PAPER_FIGURES = ROOT / "paper" / "fse2027" / "figures"
OBSERVATION_AUDIT = ROOT / "experiments" / "observation_swe_chat" / "audit" / "audit_summary.json"
CASES = Path('scaffold\\experiments\\w1_contract_corrected_v2\\cases')
FORMAL = Path('runs/mostly-correct-formal150-api_02-gpt56sol-20260903-r1')
REFRESH = Path('runs/mostly-correct-refresh-fixed150-api_02-gpt56sol-20260903-r1')
RECOVERY = Path('runs/mostly-correct-refresh-fixed-recovery4-api_02-gpt56sol-20260904-r1')


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def episode_key(row: dict) -> tuple[str, str, int]:
    return row["case_id"], row["arm"], int(row["trial"])


def accepted(row: dict) -> bool:
    return bool(row["task_success"] or row["acceptable_safe_terminal"])


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def bootstrap_difference(a: np.ndarray, b: np.ndarray, seed: int = 20260904) -> list[float]:
    rng = np.random.default_rng(seed)
    delta = a.astype(float) - b.astype(float)
    samples = rng.choice(delta, size=(100_000, len(delta)), replace=True).mean(axis=1)
    return [float(x) for x in np.quantile(samples, [0.025, 0.975])]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    PAPER_FIGURES.mkdir(parents=True, exist_ok=True)

    case_meta = {}
    case_objects = {}
    for path in CASES.glob("*.json"):
        case = read_json(path)
        case_objects[case["case_id"]] = case
        case_meta[case["case_id"]] = {
            "domain": case["domain"],
            "operator": case["corruption_operator"],
            "should_act": bool(case["expected"]["correct"]["episode"]["task_success"]),
        }
    assert len(case_meta) == 150
    assert sum(item["should_act"] for item in case_meta.values()) == 105

    formal_summary = read_json(FORMAL / "pilot_summary.json")
    refresh_summary = read_json(REFRESH / "pilot_summary.json")
    recovery_summary = read_json(RECOVERY / "pilot_summary.json")
    refresh_manifest = read_json(REFRESH / "manifest.json")
    failed_keys = {
        (state["spec"]["case_id"], state["spec"]["condition"], int(state["spec"]["trial"]))
        for state in refresh_manifest["episodes"].values()
        if state["status"] == "FAILED_TERMINAL"
    }
    assert len(failed_keys) == 5

    by_key = {episode_key(row): row for row in refresh_summary["records"]}
    recovery_by_key = {episode_key(row): row for row in recovery_summary["records"]}
    for key in failed_keys:
        assert key not in by_key
        assert key in recovery_by_key
        by_key[key] = recovery_by_key[key]

    wanted_formal = {
        "correct": "vanilla_correct",
        "corrupted": "vanilla_corrupted",
        "statewise_correct": "statewise_correct",
        "statewise_v2_contract_corrected_typedfix": "statewise_corrupted",
    }
    records: list[dict] = []
    for row in formal_summary["records"]:
        if row["arm"] not in wanted_formal:
            continue
        item = dict(row)
        item["arm"] = wanted_formal[row["arm"]]
        records.append(item)
    for row in by_key.values():
        item = dict(row)
        item["arm"] = "refresh_correct" if row["arm"] == "live_refresh_correct" else "refresh_corrupted"
        records.append(item)

    arms = (
        "vanilla_correct", "refresh_correct", "statewise_correct",
        "vanilla_corrupted", "refresh_corrupted", "statewise_corrupted",
    )
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in records:
        grouped[row["arm"]].append(row)
    assert all(len(grouped[arm]) == 150 for arm in arms), {arm: len(grouped[arm]) for arm in arms}

    metrics = []
    compact_rows = []
    for arm in arms:
        arm_rows = sorted(grouped[arm], key=lambda row: row["case_id"])
        should_act_rows = [row for row in arm_rows if case_meta[row["case_id"]]["should_act"]]
        metrics.append({
            "arm": arm,
            "episodes": len(arm_rows),
            "overall_correct_n": sum(accepted(row) for row in arm_rows),
            "overall_correct_pct": 100 * sum(accepted(row) for row in arm_rows) / len(arm_rows),
            "should_act_n": len(should_act_rows),
            "should_act_success_n": sum(bool(row["task_success"]) for row in should_act_rows),
            "should_act_completion_pct": 100 * sum(bool(row["task_success"]) for row in should_act_rows) / len(should_act_rows),
            "unsafe_n": sum(bool(row["safety_violation"]) for row in arm_rows),
            "unsafe_pct": 100 * sum(bool(row["safety_violation"]) for row in arm_rows) / len(arm_rows),
            "repair_episode_n": sum(bool(row["repair_performed"]) for row in arm_rows),
            "repair_rate_pct": 100 * sum(bool(row["repair_performed"]) for row in arm_rows) / len(arm_rows),
            "interactions_total": sum(int(row["questions"]) + int(row["permission_interactions"]) for row in arm_rows),
            "interactions_per_episode": sum(int(row["questions"]) + int(row["permission_interactions"]) for row in arm_rows) / len(arm_rows),
            "calls_total": sum(int(row["api"]["calls"]) for row in arm_rows),
            "calls_per_episode": sum(int(row["api"]["calls"]) for row in arm_rows) / len(arm_rows),
            "steps_per_episode": sum(int(row["steps"]) for row in arm_rows) / len(arm_rows),
        })
        for row in arm_rows:
            compact_rows.append({
                "case_id": row["case_id"],
                "arm": arm,
                "domain": case_meta[row["case_id"]]["domain"],
                "operator": case_meta[row["case_id"]]["operator"],
                "should_act": case_meta[row["case_id"]]["should_act"],
                "overall_correct": accepted(row),
                "task_success": bool(row["task_success"]),
                "safe_terminal": bool(row["acceptable_safe_terminal"]),
                "unsafe": bool(row["safety_violation"]),
                "repair": bool(row["repair_performed"]),
                "interactions": int(row["questions"]) + int(row["permission_interactions"]),
                "calls": int(row["api"]["calls"]),
                "steps": int(row["steps"]),
            })

    indexed = {(row["case_id"], row["arm"]): row for row in compact_rows}
    contrasts = []
    comparisons = (
        ("B", "statewise_corrupted", "refresh_corrupted"),
        ("B", "statewise_corrupted", "vanilla_corrupted"),
        ("C", "statewise_correct", "refresh_correct"),
        ("C", "statewise_correct", "vanilla_correct"),
    )
    case_ids = sorted(case_meta)
    for study, arm_a, arm_b in comparisons:
        a = np.array([indexed[(case_id, arm_a)]["overall_correct"] for case_id in case_ids], dtype=bool)
        b = np.array([indexed[(case_id, arm_b)]["overall_correct"] for case_id in case_ids], dtype=bool)
        a_only = int(np.sum(a & ~b))
        b_only = int(np.sum(~a & b))
        discordant = a_only + b_only
        p_value = float(binomtest(min(a_only, b_only), discordant, 0.5).pvalue) if discordant else 1.0
        contrasts.append({
            "study": study,
            "arm_a": arm_a,
            "arm_b": arm_b,
            "a_correct_pct": 100 * float(a.mean()),
            "b_correct_pct": 100 * float(b.mean()),
            "difference_pp": 100 * float((a.astype(float) - b.astype(float)).mean()),
            "paired_bootstrap_ci_low_pp": 100 * bootstrap_difference(a, b)[0],
            "paired_bootstrap_ci_high_pp": 100 * bootstrap_difference(a, b)[1],
            "a_only": a_only,
            "b_only": b_only,
            "mcnemar_exact_p": p_value,
        })

    strata = []
    for condition, statewise_arm, refresh_arm in (
        ("correct", "statewise_correct", "refresh_correct"),
        ("corrupted", "statewise_corrupted", "refresh_corrupted"),
    ):
        for factor in ("domain", "operator"):
            values = sorted({meta[factor] for meta in case_meta.values()})
            for value in values:
                ids = [case_id for case_id in case_ids if case_meta[case_id][factor] == value]
                sw = [indexed[(case_id, statewise_arm)]["overall_correct"] for case_id in ids]
                rf = [indexed[(case_id, refresh_arm)]["overall_correct"] for case_id in ids]
                strata.append({
                    "condition": condition,
                    "factor": factor,
                    "value": value,
                    "n": len(ids),
                    "statewise_correct_pct": 100 * sum(sw) / len(sw),
                    "refresh_correct_pct": 100 * sum(rf) / len(rf),
                    "difference_pp": 100 * (sum(sw) - sum(rf)) / len(ids),
                })

    metric_by_arm = {row["arm"]: row for row in metrics}

    repair_semantics = Counter()
    for row in grouped["statewise_correct"]:
        case = case_objects[row["case_id"]]
        known_values = {case["memory_id"]: case["correct_state"]["value"]}
        known_values.update({item["id"]: item.get("value") for item in case.get("context_memories", [])})
        for event in row["repair_alignment_events"]:
            superseded = event.get("supersedes") or []
            if not isinstance(superseded, list):
                superseded = [superseded]
            old_values = [known_values[item] for item in superseded if item in known_values]
            if not old_values:
                repair_semantics["missing_old_value"] += 1
            elif event.get("value") in old_values:
                repair_semantics["same_semantic_value"] += 1
            else:
                repair_semantics["changed_semantic_value"] += 1
    assert sum(repair_semantics.values()) == 108
    mix_rows = []
    for prevalence in (0.0, 0.05, 0.10, 0.25, 0.50, 1.0):
        for method in ("vanilla", "refresh", "statewise"):
            correct = metric_by_arm[f"{method}_correct"]["overall_correct_pct"]
            corrupted = metric_by_arm[f"{method}_corrupted"]["overall_correct_pct"]
            mix_rows.append({
                "corrupted_prevalence_pct": 100 * prevalence,
                "method": method,
                "expected_overall_correct_pct": (1.0 - prevalence) * correct + prevalence * corrupted,
            })

    write_csv(OUT / "per_episode.csv", compact_rows)
    write_csv(OUT / "metrics.csv", metrics)
    write_csv(OUT / "paired_contrasts.csv", contrasts)
    write_csv(OUT / "stratified_statewise_vs_refresh.csv", strata)
    write_csv(OUT / "mixed_workload.csv", mix_rows)

    provenance = {
        "formal_frozen_run": str(FORMAL),
        "fixed_refresh_run": str(REFRESH),
        "fixed_refresh_recovery_run": str(RECOVERY),
        "refresh_failed_cells_replaced": [list(key) for key in sorted(failed_keys)],
        "refresh_recovery_complete": True,
        "refresh_recovery_pairing_valid": bool(recovery_summary["pairing_valid"]),
        "case_count": len(case_meta),
        "should_act_count": sum(meta["should_act"] for meta in case_meta.values()),
        "should_stop_count": sum(not meta["should_act"] for meta in case_meta.values()),
        "statewise_correct_repair_semantics": dict(repair_semantics),
        "metrics": metrics,
        "paired_contrasts": contrasts,
    }
    (OUT / "results.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")

    source_paths = (
        ROOT / "experiments" / "observation_swe_chat" / "pilot100" / "sample_manifest.json",
        ROOT / "experiments" / "observation_swe_chat" / "model_annotations" / "annotation_codex.csv",
        ROOT / "experiments" / "observation_swe_chat" / "audit" / "audit_summary.json",
        FORMAL / "manifest.json",
        FORMAL / "pilot_summary.json",
        REFRESH / "manifest.json",
        REFRESH / "pilot_summary.json",
        RECOVERY / "manifest.json",
        RECOVERY / "pilot_summary.json",
    )
    source_manifest = {
        "schema_version": "motivation-abc-source-manifest-v1",
        "files": [
            {"path": str(path.resolve()), "sha256": sha256(path), "bytes": path.stat().st_size}
            for path in source_paths
        ],
    }
    (OUT / 'source_manifest.json').write_text(
        json.dumps(source_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    colors = ["#9AA0A6", "#4C78A8", "#C43C39"]
    observation = read_json(OBSERVATION_AUDIT)
    funnel_labels = ["Sampled", "State dependency", "Conflict + action", "Model candidates", "Structural audit"]
    funnel_values = [100, 93, 68, observation["raw_positive_sessions"], observation["structurally_clean_positive_sessions"]]

    fig, axes = plt.subplots(1, 3, figsize=(7.1, 2.7), gridspec_kw={"width_ratios": [1.2, 1.0, 1.0]})
    axis = axes[0]
    y = np.arange(len(funnel_labels))
    funnel_colors = ["#BAC2CA", "#94A8BC", "#6E8FAC", "#4C78A8", "#C43C39"]
    bars = axis.barh(y, funnel_values, color=funnel_colors)
    axis.set_yticks(y, funnel_labels, fontsize=7)
    axis.invert_yaxis()
    axis.set_xlim(0, 108)
    axis.set_xlabel("Sessions", fontsize=8)
    axis.set_title("A. Real trajectories", fontsize=9, weight="bold")
    axis.grid(axis="x", alpha=0.2, linewidth=0.7)
    for bar, value in zip(bars, funnel_values):
        axis.text(value + 1.3, bar.get_y() + bar.get_height() / 2, str(value), va="center", fontsize=7)

    for axis, condition, title in (
        (axes[1], "corrupted", "B. Corrupted state"),
        (axes[2], "correct", "C. Mostly-correct state"),
    ):
        condition_arms = [f"vanilla_{condition}", f"refresh_{condition}", f"statewise_{condition}"]
        values = [metric_by_arm[arm]["overall_correct_pct"] for arm in condition_arms]
        unsafe = [metric_by_arm[arm]["unsafe_pct"] for arm in condition_arms]
        x = np.arange(3)
        width = 0.34
        bars1 = axis.bar(x - width / 2, values, width, color=colors)
        bars2 = axis.bar(x + width / 2, unsafe, width, color=colors, alpha=0.38, hatch="//")
        axis.set_title(title, fontsize=9, weight="bold")
        axis.set_xticks(x, ["Untreated", "Refresh", "StateWise"], rotation=18, ha="right", fontsize=7)
        axis.set_ylim(0, 100)
        axis.grid(axis="y", alpha=0.2, linewidth=0.7)
        axis.tick_params(axis="y", labelsize=7)
        for bars_here in (bars1, bars2):
            for bar in bars_here:
                height = bar.get_height()
                axis.text(bar.get_x() + bar.get_width() / 2, height + 1.4, f"{height:.0f}", ha="center", va="bottom", fontsize=6.5)
    axes[1].set_ylabel("Episodes (%)", fontsize=8)
    handles = [
        plt.Rectangle((0, 0), 1, 1, color="#666666"),
        plt.Rectangle((0, 0), 1, 1, color="#666666", alpha=0.38, hatch="//"),
    ]
    fig.legend(handles, ["Correct outcome", "Unsafe action"], loc="upper center", ncol=2, frameon=False, fontsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.88), w_pad=1.1)
    for suffix in ("pdf", "png"):
        fig.savefig(PAPER_FIGURES / f"fig_motivation_evidence.{suffix}", dpi=300, bbox_inches="tight")
    plt.close(fig)

    print(json.dumps({"metrics": metrics, "contrasts": contrasts}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
