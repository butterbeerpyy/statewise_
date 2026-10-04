from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
FIG_OUT = HERE.parents[1] / 'results' / "figures"
PAPER_OUT = HERE.parents[2] / "paper" / "fse2027" / "figures"
for directory in (FIG_OUT, PAPER_OUT):
    directory.mkdir(parents=True, exist_ok=True)

COLORS = ("#0072B2", "#E69F00")
STATEWISE_EDGE = "#CC3311"


def read_rows() -> list[dict[str, str]]:
    with (HERE / "figure_deployment_frontier.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle))
    return sorted(rows, key=lambda row: row["method"] == "StateWise")


def style_axis(ax: plt.Axes) -> None:
    ax.set_axisbelow(True)
    ax.grid(axis="x", color="#D9DDE3", linewidth=0.6)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#7B8490")
    ax.tick_params(axis="y", length=0, labelsize=7.0)
    ax.tick_params(axis="x", labelsize=6.8)
    ax.set_xlim(0, 120)


def annotate(ax: plt.Axes, bars) -> None:
    for bar in bars:
        value = bar.get_width()
        if value < 8:
            continue
        ax.text(
            min(value + 1.2, 116),
            bar.get_y() + bar.get_height() / 2,
            f"{value:.1f}",
            va="center",
            fontsize=5.8,
            color="#374151",
        )


def draw_panel(
    ax: plt.Axes,
    rows: list[dict[str, str]],
    first_field: str,
    second_field: str,
    first_label: str,
    second_label: str,
    title: str,
) -> None:
    style_axis(ax)
    y = np.arange(len(rows))
    height = 0.36
    first = [float(row[first_field]) for row in rows]
    second = [float(row[second_field]) for row in rows]
    bars_first = ax.barh(
        y - height / 2, first, height, color=COLORS[0], label=first_label
    )
    bars_second = ax.barh(
        y + height / 2, second, height, color=COLORS[1], label=second_label
    )


    for bars in (bars_first, bars_second):
        bars[-1].set_edgecolor(STATEWISE_EDGE)
        bars[-1].set_linewidth(1.4)
        annotate(ax, bars)

    ax.set_yticks(y, [row["method"] for row in rows])
    ax.invert_yaxis()
    ax.set_xlabel("Episodes / interactions per 100 episodes", fontsize=7.2)
    ax.set_title(title, fontsize=8.3, fontweight="bold", pad=25)
    ax.legend(
        frameon=False,
        loc="lower center",
        bbox_to_anchor=(0.5, 1.01),
        ncol=2,
        fontsize=6.4,
        handlelength=1.5,
        columnspacing=1.0,
    )


def main() -> None:
    rows = read_rows()
    fig, axes = plt.subplots(1, 2, figsize=(7.15, 4.25), sharey=True)
    draw_panel(
        axes[0],
        rows,
        "panel_a_y_safe_completion_pct",
        "panel_a_x_unsafe_action_pct",
        "Safe completion",
        "Unsafe action",
        "(a) Capability and safety",
    )
    draw_panel(
        axes[1],
        rows,
        "panel_b_y_safe_completions_per_100_episodes",
        "panel_b_x_interactions_per_100_episodes",
        "Safe completions",
        "Human interactions",
        "(b) Capability and supervision cost",
    )
    fig.subplots_adjust(left=0.16, right=0.99, top=0.84, bottom=0.12, wspace=0.22)
    for destination in (FIG_OUT, PAPER_OUT):
        fig.savefig(
            destination / "fig_deployment_frontier.pdf",
            bbox_inches="tight",
            pad_inches=0.03,
        )
    fig.savefig(
        FIG_OUT / "fig_deployment_frontier.png",
        dpi=320,
        bbox_inches="tight",
        pad_inches=0.03,
    )
    plt.close(fig)
    print("wrote grouped-bar Figure 4 to both figure directories")


if __name__ == "__main__":
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8,
            "axes.linewidth": 0.7,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    main()
