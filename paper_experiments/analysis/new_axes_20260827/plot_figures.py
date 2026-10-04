from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent
OUT = Path(__file__).resolve().parents[2] / 'results' / 'figures'
PAPER_OUT = Path(__file__).resolve().parents[3] / 'paper' / 'fse2027' / 'figures'
OUT.mkdir(parents=True, exist_ok=True)
PAPER_OUT.mkdir(parents=True, exist_ok=True)

COLORS = ['#3568a9', '#d8872f', '#4f8a6f']
GREY = '#98a2b3'


def read_csv(name: str) -> list[dict[str, str]]:
    with (ROOT / name).open(newline='', encoding='utf-8') as fh:
        return list(csv.DictReader(fh))


def save(fig: plt.Figure, stem: str) -> None:
    for dest in (OUT, PAPER_OUT):
        fig.savefig(dest / ('%s.pdf' % stem), bbox_inches='tight',
                    pad_inches=0.03)
    fig.savefig(OUT / ('%s.png' % stem), dpi=320, bbox_inches='tight',
                pad_inches=0.03)
    plt.close(fig)
    print('wrote %s' % stem)


def style_axis(ax: plt.Axes) -> None:
    ax.set_ylim(0, 109)
    ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.grid(axis='y', color='#d9dde3', linewidth=0.6)
    ax.set_axisbelow(True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#7b8490')
    ax.spines['bottom'].set_color('#7b8490')


def operator_robustness() -> None:

    rows = read_csv('operator_matrix.csv')
    short = {'Wrong value': 'Wrong\nvalue', 'Stale value': 'Stale\nvalue',
             'Over-generalization': 'Over-\ngen.',
             'Joint policy collapse': 'Joint\npolicy',
             'Implicit conflict': 'Implicit\nconflict',
             'Scope mismatch': 'Scope\nmismatch'}
    labels = ['%s\n(n=%s)' % (short[r['operator']], r['cases']) for r in rows]
    series = [
        ('Corrupted memory', [float(r['Corrupted memory_obj']) for r in rows]),
        ('Best baseline', None),
        ('StateWise', [float(r['StateWise_obj']) for r in rows]),
    ]

    baseline_cols = ['Corrupted memory_obj', 'No memory_obj',
                     'Bare approval_obj', 'Rationale approval_obj',
                     'Clarification_obj', 'MemLineage_obj',
                     'Safety Sentry_obj', 'Ask-or-Assume_obj']
    series[1] = ('Best baseline',
                 [max(float(r[c]) for c in baseline_cols) for r in rows])

    fig, ax = plt.subplots(1, 1, figsize=(3.3, 2.2))
    style_axis(ax)
    x = np.arange(len(rows))
    width = 0.26
    for i, ((name, vals), color) in enumerate(zip(series, COLORS)):
        bars = ax.bar(x + (i - 1) * width, vals, width, color=color,
                      label=name, linewidth=0.9)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, v + 1.2, '%.0f' % v,
                    ha='center', va='bottom', fontsize=6.0, color='#2d333b')
    ax.set_xticks(x, labels)
    ax.tick_params(axis='x', labelsize=6.0, pad=2)
    ax.set_ylabel('Objective correctness (%)', fontsize=7.5)
    handles, lab = ax.get_legend_handles_labels()
    fig.legend(handles, lab, frameon=False, loc='upper center',
               bbox_to_anchor=(0.5, 0.995), ncol=3, fontsize=6.7,
               handlelength=1.4, columnspacing=0.8)
    fig.subplots_adjust(left=0.13, right=0.99, top=0.84, bottom=0.20)
    save(fig, 'fig_operator_robustness')


def rq4_stratum() -> None:

    rows = read_csv('rq4_stratum.csv')
    labels = [r['arm'].replace('Full StateWise', 'Full')
              .replace('w/o Persistent Repair', 'w/o Repair')
              .replace('w/o Typed Grounding', 'w/o Typed gr.')
              .replace('w/o Attribution', 'w/o Attrib.')
              .replace('w/o Resolution', 'w/o Resol.') for r in rows]
    series = [
        ('Runtime', [float(r['runtime']) for r in rows]),
        ('Workspace', [float(r['workspace']) for r in rows]),
        ('Git', [float(r['git']) for r in rows]),
    ]
    fig, ax = plt.subplots(1, 1, figsize=(3.3, 2.2))
    style_axis(ax)
    x = np.arange(len(rows))
    width = 0.26
    for i, ((name, vals), color) in enumerate(zip(series, COLORS)):
        bars = ax.bar(x + (i - 1) * width, vals, width, color=color,
                      label=name,
                      edgecolor=['#111827' if j == 0 else 'none'
                                 for j in range(len(rows))],
                      linewidth=0.9)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, v + 1.2, '%.0f' % v,
                    ha='center', va='bottom', fontsize=6.0, color='#2d333b')
    ax.set_xticks(x, labels)
    ax.tick_params(axis='x', labelsize=6.2, pad=2)
    ax.set_ylabel('Objective correctness (%)', fontsize=7.5)
    handles, lab = ax.get_legend_handles_labels()
    fig.legend(handles, lab, frameon=False, loc='upper center',
               bbox_to_anchor=(0.5, 0.995), ncol=3, fontsize=6.7,
               handlelength=1.4, columnspacing=0.8)
    fig.subplots_adjust(left=0.13, right=0.99, top=0.84, bottom=0.17)
    save(fig, 'fig_rq4_stratum')


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
    operator_robustness()
    rq4_stratum()
