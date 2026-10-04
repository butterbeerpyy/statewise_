from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent
OUT = Path(__file__).resolve().parents[2] / 'results' / "figures"
PAPER_OUT = Path(__file__).resolve().parents[3] / "paper" / "fse2027" / "figures"
OUT.mkdir(parents=True, exist_ok=True)
PAPER_OUT.mkdir(parents=True, exist_ok=True)

COLORS = ["#3568a9", "#d8872f", "#4f8a6f"]


def read_csv(name: str) -> list[dict[str, str]]:
    with (ROOT / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def save(fig: plt.Figure, stem: str) -> None:
    for destination in (OUT, PAPER_OUT):
        fig.savefig(destination / f"{stem}.pdf", bbox_inches="tight", pad_inches=0.03)
    fig.savefig(OUT / f"{stem}.png", dpi=320, bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)


def style_axis(ax: plt.Axes) -> None:
    ax.set_ylim(0, 109)
    ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.set_ylabel("Rate (%)")
    ax.grid(axis="y", color="#d9dde3", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#7b8490")
    ax.spines["bottom"].set_color("#7b8490")


def add_value_labels(ax: plt.Axes, bars, values: list[float]) -> None:
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 1.2,
            f"{value:.0f}",
            ha="center",
            va="bottom",
            fontsize=6.4,
            color="#2d333b",
        )


def _outcome_panel(ax: plt.Axes, series, indices, labels, title: str | None = None) -> None:
    width = 0.245
    style_axis(ax)
    x = np.arange(len(indices))
    for series_index, ((name, all_values), color) in enumerate(zip(series, COLORS)):
        values = [all_values[index] for index in indices]
        bars = ax.bar(
            x + (series_index - 1) * width,
            values,
            width,
            color=color,
            label=name,
            edgecolor=["#111827" if index == 9 else "none" for index in indices],
            linewidth=0.9,
        )
        add_value_labels(ax, bars, values)
    if title:
        ax.set_title(title, fontsize=8, color="#4b5563", pad=3)
    ax.set_xticks(x, labels)
    ax.tick_params(axis="x", labelsize=6.8, pad=2)
    ax.set_ylabel("Rate (%)", fontsize=7.5)


def primary_grouped_bars() -> None:
    rows = read_csv("primary_claim_matrix.csv")
    series = [
        ("Objective", [float(row["objective_correctness"]) for row in rows]),
        ("Completion", [float(row["action_completion"]) for row in rows]),
        ("No violation", [float(row["no_violation"]) for row in rows]),
    ]
    fig, axes = plt.subplots(2, 1, figsize=(3.3, 3.9), sharey=True)
    _outcome_panel(axes[0], series, [0, 1, 2], ["Correct", "Corrupted", "No memory"], "Memory controls")
    _outcome_panel(axes[1], series, [3, 4, 5], ["Bare", "Rationale", "Clarification"], "Action layer")
    handles, legend_labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles, legend_labels, frameon=False, loc="upper center",
        bbox_to_anchor=(0.5, 0.995), ncol=3, fontsize=6.7,
        handlelength=1.4, columnspacing=0.8,
    )
    fig.subplots_adjust(left=0.15, right=0.99, top=0.87, bottom=0.08, hspace=0.42)
    save(fig, "fig_claim_memory_action")

    fig, ax = plt.subplots(1, 1, figsize=(3.3, 2.35))
    _outcome_panel(
        ax,
        series,
        [6, 7, 8, 9],
        ["MemLineage", "Safety", "Ask/Assume", "StateWise"],
    )
    handles, legend_labels = ax.get_legend_handles_labels()
    fig.legend(
        handles, legend_labels, frameon=False, loc="upper center",
        bbox_to_anchor=(0.5, 0.995), ncol=3, fontsize=6.7,
        handlelength=1.4, columnspacing=0.8,
    )
    fig.subplots_adjust(left=0.15, right=0.99, top=0.82, bottom=0.16)
    save(fig, "fig_claim_system_safeguards")


def rq4_grouped_bars() -> None:
    included = {
        "Full StateWise",
        "w/o Attribution",
        "w/o Resolution",
        "w/o Persistent Repair",
        "w/o Typed Grounding",
    }
    rows = [row for row in read_csv("rq4_component_matrix.csv") if row["arm"] in included]
    rows = [row for row in rows if row["arm"] != "Full StateWise"]
    labels = ["Attribution", "Resolution", "Persistent repair", "Typed grounding"]
    effects = np.array([-float(row["delta_objective"]) for row in rows])
    lows = np.array([float(row["paired_ci_low"]) for row in rows])
    highs = np.array([float(row["paired_ci_high"]) for row in rows])
    y = np.arange(len(rows))[::-1]
    fig, ax = plt.subplots(1, 1, figsize=(3.3, 2.25))
    ax.axvline(0, color="#4b5563", linewidth=0.8, linestyle="--")
    ax.errorbar(
        effects,
        y,
        xerr=np.vstack([effects - lows, highs - effects]),
        fmt="o",
        color="#3568a9",
        ecolor="#4b5563",
        elinewidth=1.2,
        capsize=3,
        markersize=5,
    )
    for value, upper, ypos in zip(effects, highs, y):
        ax.text(upper + 1.5, ypos, f"{value:.1f}", va="center", fontsize=7)
    ax.set_yticks(y, labels)
    ax.set_xlim(-5, 90)
    ax.set_xticks([0, 20, 40, 60, 80])
    ax.set_xlabel("Paired objective-correctness loss (pp)")
    ax.grid(axis="x", color="#d9dde3", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0, labelsize=7)
    fig.subplots_adjust(left=0.35, right=0.98, top=0.97, bottom=0.23)
    save(fig, "fig_claim_component_ablation")


if __name__ == "__main__":
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 8,
        "axes.labelsize": 8,
        "axes.linewidth": 0.7,
        "xtick.major.width": 0.7,
        "ytick.major.width": 0.7,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })
    primary_grouped_bars()
    rq4_grouped_bars()
