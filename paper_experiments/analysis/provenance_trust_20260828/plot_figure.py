from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
OUT = Path(__file__).resolve().parents[2] / 'results' / 'figures'
PAPER_OUT = Path(__file__).resolve().parents[3] / 'paper' / 'fse2027' / 'figures'
OUT.mkdir(parents=True, exist_ok=True)
PAPER_OUT.mkdir(parents=True, exist_ok=True)

COLORS = ['#3568a9', '#d8872f', '#4f8a6f', '#8a6f4f']
CELLS = ['LS', 'LC', 'HS', 'HC', 'US']
LABELS = {
    'LS': 'low trust\nstale',
    'LC': 'low trust\ncorrect',
    'HS': 'HIGH trust\nstale',
    'HC': 'HIGH trust\ncorrect',
    'US': 'untrusted\nstale',
}
ORDER = ['StateWise', 'MemLineage', 'Corrupted memory', 'Rationale approval']
SHORT = {'StateWise': 'StateWise', 'MemLineage': 'MemLineage',
         'Corrupted memory': 'Corrupted', 'Rationale approval': 'Rationale'}


def read(name: str) -> dict[str, dict[str, float]]:
    with (HERE / name).open(newline='', encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))
    out = {}
    for row in rows:
        method = row['method']
        out[method] = {c: float(row[c]) for c in CELLS if row.get(c)}
    return out


def save(fig: plt.Figure, stem: str) -> None:
    for dest in (OUT, PAPER_OUT):
        fig.savefig(dest / ('%s.pdf' % stem), bbox_inches='tight',
                    pad_inches=0.03)
    fig.savefig(OUT / ('%s.png' % stem), dpi=320, bbox_inches='tight',
                pad_inches=0.03)
    plt.close(fig)
    print('wrote %s' % stem)


def style(ax: plt.Axes) -> None:
    ax.set_ylim(0, 109)
    ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.grid(axis='y', color='#d9dde3', linewidth=0.6)
    ax.set_axisbelow(True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#7b8490')
    ax.spines['bottom'].set_color('#7b8490')


def panel(ax: plt.Axes, data: dict[str, dict[str, float]], ylabel: str,
          annotate_hs: bool) -> None:
    style(ax)
    x = np.arange(len(CELLS))
    width = 0.2
    for i, method in enumerate(ORDER):
        vals = [data.get(method, {}).get(c, 0.0) for c in CELLS]
        bars = ax.bar(x + (i - 1.5) * width, vals, width, color=COLORS[i],
                      label=SHORT[method], linewidth=0.9)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, v + 1.2, '%.0f' % v,
                    ha='center', va='bottom', fontsize=5.4, color='#2d333b')
    ax.set_xticks(x, [LABELS[c] for c in CELLS])
    ax.tick_params(axis='x', labelsize=6.0, pad=2)
    ax.set_ylabel(ylabel, fontsize=7.2)
    if annotate_hs:

        ax.axvspan(1.6, 2.4, color='#c0392b', alpha=0.07, zorder=0)


def main() -> None:
    obj = read('cell_objective.csv')
    viol = read('cell_violation.csv')
    fig, axes = plt.subplots(2, 1, figsize=(3.3, 3.6), sharex=True)
    panel(axes[0], obj, 'Objective correctness (%)', True)
    panel(axes[1], viol, 'Safety violation (%)', True)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, loc='upper center',
               bbox_to_anchor=(0.5, 0.997), ncol=4, fontsize=6.0,
               handlelength=1.2, columnspacing=0.7)
    fig.subplots_adjust(left=0.15, right=0.99, top=0.90, bottom=0.10,
                        hspace=0.16)
    save(fig, 'fig_provenance_trust')


if __name__ == '__main__':
    plt.rcParams.update({
        'font.family': 'DejaVu Sans',
        'font.size': 8,
        'axes.labelsize': 8,
        'axes.linewidth': 0.7,
        'xtick.major.width': 0.7,
        'ytick.major.width': 0.7,
        'pdf.fonttype': 42,
        'ps.fonttype': 42,
    })
    main()
