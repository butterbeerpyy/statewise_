from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


SOURCE = Path('runs/formal_v10_rq4_ablations150_gpt56sol_20260822_r1')
OUT_DIR = Path("paper/fse2027/figures")
AUDIT_DIR = Path('paper_experiments/analysis/restructure_audit_20260829')
ARMS = [
    ("statewise_v2_contract_corrected_typedfix", "Full StateWise"),
    ("statewise_ablation_no_attribution", "w/o Attribution"),
    ("statewise_ablation_no_resolution", "w/o Resolution"),
    ("statewise_ablation_no_repair", "w/o Persistent Repair"),
    ("statewise_ablation_no_typed_grounding", "w/o Typed Grounding"),
]


def objective(row: dict) -> bool:
    return bool(
        (row.get("risk_adjusted_task_success") or row.get("acceptable_safe_terminal"))
        and not row.get("safety_violation")
    )


def main() -> None:
    summary = json.loads((SOURCE / "pilot_summary.json").read_text(encoding="utf-8"))
    cases_root = Path(summary["dataset"]["cases_root"])
    records = summary["records"]
    case_ids = sorted({row["case_id"] for row in records})
    should_act = set()
    for case_id in case_ids:
        case = json.loads(
            (cases_root / f"{case_id}.json").read_text(encoding="utf-8")
        )
        if bool(
            (((case.get("expected") or {}).get("correct") or {}).get("episode") or {})
            .get("task_success")
        ):
            should_act.add(case_id)
    assert len(case_ids) == 150
    assert len(should_act) == 125

    rows = []
    for arm, label in ARMS:
        selected = [row for row in records if row["arm"] == arm]
        assert len(selected) == 150
        act = [row for row in selected if row["case_id"] in should_act]
        rows.append({
            "arm": arm,
            "label": label,
            "overall_pct": 100 * sum(objective(row) for row in selected) / len(selected),
            "should_act_pct": 100 * sum(
                bool(row.get("risk_adjusted_task_success"))
                and not row.get("safety_violation") for row in act
            ) / len(act),
        })

    expected = [(93.3, 92.8), (40.0, 28.0), (14.7, 0.0), (16.7, 0.0), (66.0, 59.2)]
    for row, (overall, act) in zip(rows, expected):
        assert round(row["overall_pct"], 1) == overall
        assert round(row["should_act_pct"], 1) == act

    with (AUDIT_DIR / "rq4_bar_data.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    plotted = list(reversed(rows))
    labels = [row["label"] for row in plotted]
    overall = [row["overall_pct"] for row in plotted]
    act = [row["should_act_pct"] for row in plotted]
    y = list(range(len(plotted)))
    height = 0.34

    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 8.2,
        "axes.labelsize": 8.5,
        "xtick.labelsize": 7.8,
        "ytick.labelsize": 8.2,
        "legend.fontsize": 8.0,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })
    fig, ax = plt.subplots(figsize=(7.15, 2.85))
    bars_overall = ax.barh(
        [value + height / 2 for value in y], overall, height,
        color="#2B6CB0", edgecolor="#1A365D", linewidth=0.6,
        label="Overall correctness",
    )
    bars_act = ax.barh(
        [value - height / 2 for value in y], act, height,
        color="#BFD7EA", edgecolor="#315B7D", linewidth=0.6,
        hatch="///", label="Should-Act completion",
    )
    ax.set_yticks(y, labels)
    ax.set_xlim(0, 103)
    ax.set_xlabel("Successful outcomes (%)")
    ax.set_xticks(range(0, 101, 20))
    ax.grid(axis="x", color="#D9E1E8", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.legend(loc="lower right", frameon=False, ncol=2, bbox_to_anchor=(1.0, 1.005))

    for bars in (bars_overall, bars_act):
        for bar in bars:
            value = bar.get_width()
            ax.text(
                min(value + 1.1, 98.2), bar.get_y() + bar.get_height() / 2,
                f"{value:.1f}", va="center", ha="left", fontsize=7.2,
                color="#152536",
            )

    fig.tight_layout(pad=0.45)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_DIR / "fig_rq4_ablation_bars.pdf", bbox_inches="tight")
    fig.savefig(OUT_DIR / "fig_rq4_ablation_bars.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(json.dumps({"rows": rows, "output": str(OUT_DIR)}, indent=2))


if __name__ == "__main__":
    main()
