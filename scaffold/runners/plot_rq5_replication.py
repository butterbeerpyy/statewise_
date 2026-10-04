from __future__ import annotations

import csv
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import Rectangle
from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / 'paper_experiments/results/rq5'
PRIMARY = RESULTS / "rq5_results.xlsx"
REPLICATION = RESULTS / "rq5_v10_replication3.xlsx"
OUT_DIR = RESULTS / "figures"
SOURCE_DATA = OUT_DIR / "RQ5_replication_figure_source.csv"

METHODS = ["StateWise", "MemLineage", "Safety Sentry", "Ask-or-Assume"]
METRICS = [
    ("Strict sequence\nsuccess", "strict_rate"),
    ("Future-task\ncompletion", "future_completion"),
    ("No safety\nviolation", "future_no_violation"),
]


def _records(path: Path, sheet_name: str) -> list[dict]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    values = list(workbook[sheet_name].values)
    headers = list(values[0])
    return [dict(zip(headers, row)) for row in values[1:]]


def _load() -> list[dict]:
    primary_summary = {row["method"]: row for row in _records(PRIMARY, "Paper_Comparison")}
    replication_summary = {
        row["method"]: row for row in _records(REPLICATION, "Replication_Summary")
    }
    primary_sequences = _records(PRIMARY, "Sequence_Data")
    arm_to_method = {
        "statewise_v2_contract_corrected_typedfix": "StateWise",
        "memlineage_trust": "MemLineage",
        "safety_sentry": "Safety Sentry",
        "ask_or_assume": "Ask-or-Assume",
    }
    strict_primary = {method: 0 for method in METHODS}
    for row in primary_sequences:
        method = arm_to_method.get(row.get("arm"))
        if method and int(row.get("future_task_success_count") or 0) == 3 \
                and int(row.get("cumulative_safety_violations") or 0) == 0:
            strict_primary[method] += 1

    rows = []
    for method in METHODS:
        primary = primary_summary[method]
        replication = replication_summary[method]
        rows.extend([
            {
                "method": method,
                "run": "Primary",
                "strict_rate": strict_primary[method] / 32,
                "future_completion": float(primary["future_task_success_rate"]),
                "future_no_violation": float(primary["future_no_violation_rate"]),
            },
            {
                "method": method,
                "run": "Replication",
                "strict_rate": float(replication["all_future_safe_completion"]),
                "future_completion": float(replication["future_task_success_rate"]),
                "future_no_violation": float(replication["future_no_violation_rate"]),
            },
        ])
    return rows


def _style() -> None:
    mpl.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "DejaVu Sans"],
        "font.size": 8.5,
        "axes.titlesize": 10,
        "xtick.labelsize": 8.2,
        "ytick.labelsize": 8.6,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "none",
    })


def _text_color(value: float) -> str:
    return "white" if value >= 0.56 else "#172027"


def _draw_matrix(axis, matrix, title: str, show_rows: bool, cmap, norm) -> None:
    axis.imshow(matrix, cmap=cmap, norm=norm, interpolation="nearest", aspect="auto")
    axis.set_title(title, loc="left", pad=12, fontweight="bold")
    axis.set_xticks(range(len(METRICS)), [label for label, _ in METRICS])
    axis.xaxis.tick_top()
    axis.tick_params(axis="x", length=0, pad=7)
    axis.set_yticks(range(len(METHODS)), METHODS if show_rows else [""] * len(METHODS))
    axis.tick_params(axis="y", length=0, pad=8)
    for row_index, method in enumerate(METHODS):
        for column_index, value in enumerate(matrix[row_index]):
            axis.text(
                column_index, row_index, f"{100 * value:.1f}%",
                ha="center", va="center", color=_text_color(value),
                fontsize=10.2, fontweight="bold" if method == "StateWise" else "normal",
            )
    axis.set_xticks([index - 0.5 for index in range(1, len(METRICS))], minor=True)
    axis.set_yticks([index - 0.5 for index in range(1, len(METHODS))], minor=True)
    axis.grid(which="minor", color="white", linewidth=2.2)
    axis.tick_params(which="minor", bottom=False, left=False)
    axis.add_patch(Rectangle(
        (-0.49, -0.49), len(METRICS) - 0.02, 0.98,
        fill=False, edgecolor="#073B4C", linewidth=1.8,
    ))
    for spine in axis.spines.values():
        spine.set_visible(False)


def main() -> None:
    rows = _load()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with SOURCE_DATA.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    by_key = {(row["method"], row["run"]): row for row in rows}
    matrices = {
        run: [[by_key[(method, run)][key] for _, key in METRICS] for method in METHODS]
        for run in ("Primary", "Replication")
    }

    _style()
    cmap = LinearSegmentedColormap.from_list(
        "statewise_performance", ["#F3F5F6", "#D7E5E3", "#69AAA4", "#007C7A", "#073B4C"]
    )
    norm = Normalize(vmin=0, vmax=1)
    figure, axes = plt.subplots(1, 2, figsize=(7.15, 2.75), gridspec_kw={"wspace": 0.12})
    _draw_matrix(axes[0], matrices["Primary"], "(a) Primary run", True, cmap, norm)
    _draw_matrix(axes[1], matrices["Replication"], "(b) Independent replication", False, cmap, norm)

    colorbar_axis = figure.add_axes([0.305, 0.085, 0.39, 0.035])
    colorbar = mpl.colorbar.ColorbarBase(colorbar_axis, cmap=cmap, norm=norm, orientation="horizontal")
    colorbar.set_ticks([0, 0.5, 1])
    colorbar.set_ticklabels(["0%", "50%", "100%"])
    colorbar.ax.tick_params(length=0, pad=3, labelsize=7.5)
    colorbar.outline.set_visible(False)
    colorbar.set_label("Higher is better", labelpad=-25, y=1.6, fontsize=7.7, color="#465159")

    figure.subplots_adjust(left=0.19, right=0.99, bottom=0.23, top=0.78)
    for extension in ("png", "pdf", "svg"):
        figure.savefig(
            OUT_DIR / f"RQ5_primary_replication.{extension}",
            dpi=400 if extension == "png" else None,
            facecolor="white",
        )
    plt.close(figure)
    print((OUT_DIR / "RQ5_primary_replication.png").resolve())


if __name__ == "__main__":
    main()
