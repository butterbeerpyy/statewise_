from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[3]
FIG = ROOT / "paper" / "fse2027" / "figures"
RQ5_WORKBOOK = ROOT / 'paper_experiments' / 'results' / "rq5" / "rq5_v10_matched.xlsx"
FIG.mkdir(parents=True, exist_ok=True)

BLUE = "#3B708F"
LIGHT_BLUE = "#9BB8C8"
ORANGE = "#D17827"
GREEN = "#3F866B"
RED = "#B65353"
GRAY = "#D9DDE2"
DARK = "#27323A"

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 7.2,
        "axes.titlesize": 8.2,
        "axes.labelsize": 7.4,
        "legend.fontsize": 6.4,
        "xtick.labelsize": 6.5,
        "ytick.labelsize": 6.5,
        "axes.linewidth": 0.6,
        "savefig.dpi": 300,
        "pdf.fonttype": 42,
    }
)


def finish(fig: plt.Figure, stem: str) -> None:

    fig.savefig(FIG / f"{stem}.pdf", bbox_inches="tight", pad_inches=0.025)
    fig.savefig(FIG / f"{stem}.png", bbox_inches="tight", pad_inches=0.025)
    plt.close(fig)


def clean_axes(ax: plt.Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(color="#D8DEE3", linewidth=0.55, alpha=0.8)
    ax.set_axisbelow(True)


rq2_names = [
    "Base",
    "Ask-or-Assume",
    "CRITIC",
    "MemLineage",
    "Safety Sentry",
    "StateWise",
]
rq2_completion = np.array([11.4, 10.5, 27.6, 7.6, 3.9, 84.8])
rq2_unsafe = np.array([42.7, 42.0, 28.0, 22.7, 4.7, 0.0])
rq2_label_positions = {
    "Base": (15.5, 49.5),
    "Ask-or-Assume": (17.0, 40.0),
    "CRITIC": (33.0, 31.5),
    "MemLineage": (13.0, 26.0),
    "Safety Sentry": (10.0, 9.5),
    "StateWise": (78.0, 7.0),
}

fig, ax = plt.subplots(figsize=(3.35, 2.25), constrained_layout=True)
for name, completion, unsafe in zip(rq2_names, rq2_completion, rq2_unsafe):
    color = ORANGE if name == "StateWise" else BLUE
    ax.scatter(completion, unsafe, s=36, color=color, edgecolor="white", linewidth=0.7, zorder=3)
    label_x, label_y = rq2_label_positions[name]
    ax.annotate(
        name,
        xy=(completion, unsafe),
        xytext=(label_x, label_y),
        textcoords="data",
        ha="center",
        va="center",
        fontsize=6.5,
        color=DARK,
        arrowprops={"arrowstyle": "-", "color": "#89949C", "lw": 0.55},
    )
ax.set_xlim(0, 92)
ax.set_ylim(0, 54)
ax.set_xlabel("Should-Act completion (%)")
ax.set_ylabel("Unsafe actions (%)")
ax.set_xticks(np.arange(0, 101, 20))
ax.set_yticks(np.arange(0, 51, 10))
clean_axes(ax)
finish(fig, "fig_rq2_action_safety")


rq4_labels = [
    "w/o Attribution",
    "w/o Resolution",
    "w/o Persistent Repair",
    "w/o Typed Grounding",
    "w/o Replanning",
    "w/o Residual Gate",
]
rq4_effect = np.array([53.3, 78.7, 76.7, 27.3, 2.7, 2.7])
rq4_low = np.array([44.7, 72.0, 69.3, 19.3, -1.3, -1.3])
rq4_high = np.array([61.3, 85.3, 83.3, 35.3, 6.7, 6.7])
rq4_full_only = np.array([81, 119, 116, 45, 7, 7])
rq4_variant_only = np.array([1, 1, 1, 4, 3, 3])
rq4_significant = np.array([True, True, True, True, False, False])

fig, ax = plt.subplots(figsize=(3.35, 2.55), constrained_layout=True)
y = np.arange(len(rq4_labels))
for row in y:
    marker_face = ORANGE if rq4_significant[row] else "white"
    marker_edge = ORANGE if rq4_significant[row] else "#7C878F"
    ax.errorbar(
        rq4_effect[row],
        row,
        xerr=np.array(
            [[rq4_effect[row] - rq4_low[row]], [rq4_high[row] - rq4_effect[row]]]
        ),
        fmt="o",
        markersize=5.0,
        markerfacecolor=marker_face,
        markeredgecolor=marker_edge,
        ecolor=marker_edge,
        elinewidth=1.15,
        capsize=2.2,
        zorder=3,
    )
    ax.text(
        0.995,
        row,
        f"{rq4_full_only[row]} / {rq4_variant_only[row]}",
        transform=ax.get_yaxis_transform(),
        ha="right",
        va="center",
        fontsize=6.3,
        color=DARK,
    )
ax.axvline(0, color="#68747C", linewidth=0.8, linestyle="--")
ax.set_xlim(-7, 103)
ax.set_yticks(y, rq4_labels)
ax.invert_yaxis()
ax.set_xlabel("Overall-correctness loss vs. Full (pp)")
ax.text(
    0.995,
    1.025,
    "Full-only / variant-only",
    transform=ax.transAxes,
    ha="right",
    va="bottom",
    fontsize=6.2,
    color=DARK,
)
ax.grid(axis="x", color="#D8DEE3", linewidth=0.55, alpha=0.8)
ax.set_axisbelow(True)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.spines["left"].set_visible(False)
finish(fig, "fig_rq4_failures")


workbook = load_workbook(RQ5_WORKBOOK, read_only=True, data_only=True)
sheet = workbook["Task_Data"]
task_rows = iter(sheet.values)
task_header = next(task_rows)
task_data = [dict(zip(task_header, row)) for row in task_rows]
workbook.close()

rq5_arms = [
    ("StateWise", "statewise_v2_contract_corrected_typedfix"),
    ("MemLineage", "memlineage_trust"),
    ("Safety Sentry", "safety_sentry"),
    ("Ask-or-Assume", "ask_or_assume"),
]
domain_order = {"environment": 0, "git": 1, "database": 2, "deployment": 3}
sequence_ids = sorted(
    {
        row["sequence_id"]
        for row in task_data
        if row["arm"] == rq5_arms[0][1]
    },
    key=lambda value: (domain_order[value.split("_")[1]], value),
)
sequence_index = {sequence_id: index for index, sequence_id in enumerate(sequence_ids)}

rq5_cmap = ListedColormap([RED, GRAY, GREEN])
rq5_norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5], rq5_cmap.N)
fig, axes = plt.subplots(
    len(rq5_arms),
    1,
    figsize=(3.35, 3.85),
    sharex=True,
)
for ax, (display_name, arm_name) in zip(axes, rq5_arms):
    outcome = np.full((4, 32), 1, dtype=int)
    for row in task_data:
        if row["arm"] != arm_name:
            continue
        column = sequence_index[row["sequence_id"]]
        task = int(row["task_index"]) - 1
        if bool(row["safety_violation"]):
            outcome[task, column] = 0
        elif bool(row["risk_adjusted_task_success"]):
            outcome[task, column] = 2
    ax.imshow(outcome, cmap=rq5_cmap, norm=rq5_norm, aspect="auto", interpolation="nearest")
    for boundary in (7.5, 15.5, 23.5):
        ax.axvline(boundary, color="white", linewidth=1.3)
    ax.set_yticks(range(4), ["T1", "T2", "T3", "T4"])
    ax.set_ylabel(display_name, rotation=0, ha="right", va="center", labelpad=25, fontsize=6.5)
    ax.tick_params(axis="both", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

axes[0].text(3.5, -1.0, "Env.", ha="center", va="bottom", fontsize=6.2)
axes[0].text(11.5, -1.0, "Git", ha="center", va="bottom", fontsize=6.2)
axes[0].text(19.5, -1.0, "DB", ha="center", va="bottom", fontsize=6.2)
axes[0].text(27.5, -1.0, "Deploy.", ha="center", va="bottom", fontsize=6.2)
axes[-1].set_xticks([0, 7, 15, 23, 31], ["1", "8", "16", "24", "32"])
axes[-1].set_xlabel("Sequence", labelpad=3)
fig.subplots_adjust(left=0.31, right=0.99, top=0.93, bottom=0.16, hspace=0.23)
fig.legend(
    handles=[
        Patch(facecolor=GREEN, label="Safe success"),
        Patch(facecolor=GRAY, label="Safe incomplete"),
        Patch(facecolor=RED, label="Violation"),
    ],
    loc="lower center",
    bbox_to_anchor=(0.5, 0.01),
    ncol=3,
    frameon=False,
    handlelength=1.0,
    columnspacing=0.9,
)
finish(fig, "fig_rq5_sequence_matrix")


rq6_dimensions = ["Repositories", "Tool operations", "State types", "Configurations"]
rq6_dev = np.array([46.7, 60.0, 25.0, 22.9])
rq6_unseen = np.array([53.3, 40.0, 75.0, 77.1])
rq6_slices = [
    "All held-out configurations",
    "Any unseen",
    "Composition-only unseen",
    "Fully unseen",
    "New repositories",
    "Unseen tool operations",
    "Unseen state types",
    "Development-seen",
]
rq6_overall = np.array([93.4, 95.7, 76.9, 97.0, 98.4, 93.3, 95.1, 93.2])
rq6_should_act = np.array([92.6, 95.6, 76.9, 92.9, 97.7, 90.0, 92.6, 93.2])

fig, (coverage_ax, performance_ax) = plt.subplots(
    2,
    1,
    figsize=(3.35, 4.15),
    gridspec_kw={"height_ratios": [1.0, 1.55]},
    constrained_layout=True,
)

y_coverage = np.arange(len(rq6_dimensions))
coverage_ax.barh(y_coverage, rq6_dev, color=LIGHT_BLUE, label="Seen in Dev40")
coverage_ax.barh(
    y_coverage,
    rq6_unseen,
    left=rq6_dev,
    color=ORANGE,
    label="Unseen in Dev40",
)
coverage_ax.set_yticks(y_coverage, rq6_dimensions)
coverage_ax.invert_yaxis()
coverage_ax.set_xlim(0, 100)
coverage_ax.set_xlabel("Share of Main150 units (%)")
coverage_ax.set_title("(a) Interface coverage", loc="left")
coverage_ax.text(rq6_dev[0] / 2, 0, "Seen in Dev40", ha="center", va="center", fontsize=6.1, color=DARK)
coverage_ax.text(
    rq6_dev[0] + rq6_unseen[0] / 2,
    0,
    "Unseen in Dev40",
    ha="center",
    va="center",
    fontsize=6.1,
    color="white",
)
coverage_ax.grid(axis="x", color="#D8DEE3", linewidth=0.55, alpha=0.8)
coverage_ax.set_axisbelow(True)
coverage_ax.spines["top"].set_visible(False)
coverage_ax.spines["right"].set_visible(False)
coverage_ax.spines["left"].set_visible(False)

y_performance = np.arange(len(rq6_slices))
performance_ax.scatter(
    rq6_overall,
    y_performance - 0.12,
    s=28,
    color=BLUE,
    marker="o",
    label="Overall",
    zorder=3,
)
performance_ax.scatter(
    rq6_should_act,
    y_performance + 0.12,
    s=28,
    facecolor="white",
    edgecolor=ORANGE,
    linewidth=1.0,
    marker="s",
    label="Should-Act",
    zorder=3,
)
performance_ax.set_yticks(y_performance, rq6_slices)
performance_ax.invert_yaxis()
performance_ax.set_xlim(70, 100)
performance_ax.set_xlabel("Correctness (%)")
performance_ax.set_title("(b) Independent Main150 slices", loc="left")
performance_ax.legend(loc="lower left", frameon=False)
performance_ax.grid(axis="x", color="#D8DEE3", linewidth=0.55, alpha=0.8)
performance_ax.set_axisbelow(True)
performance_ax.spines["top"].set_visible(False)
performance_ax.spines["right"].set_visible(False)
performance_ax.spines["left"].set_visible(False)
finish(fig, "fig_rq6_generalization")
