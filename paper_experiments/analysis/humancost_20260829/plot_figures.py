from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
CURVE = HERE.parent / 'gate_curve_20260829'
OUT = HERE.parents[1] / 'results' / 'figures'
OUT.mkdir(parents=True, exist_ok=True)

BLUE, ORANGE, GREEN = '#3568a9', '#d8872f', '#4f8a6f'
GREY = '#98a2b3'


def read(path: Path) -> list[dict[str, str]]:
    with path.open(newline='', encoding='utf-8') as fh:
        return list(csv.DictReader(fh))


def save(fig: plt.Figure, stem: str) -> None:
    fig.savefig(OUT / ('%s.pdf' % stem), bbox_inches='tight', pad_inches=0.03)
    fig.savefig(OUT / ('%s.png' % stem), dpi=320, bbox_inches='tight',
                pad_inches=0.03)
    plt.close(fig)
    print('wrote %s' % stem)


def humancost_scatter() -> None:

    rows = read(HERE / 'humancost_single_episode.csv')
    fig, ax = plt.subplots(1, 1, figsize=(3.4, 2.6))
    ax.grid(color='#d9dde3', linewidth=0.6)
    ax.set_axisbelow(True)
    for spine in ('top', 'right'):
        ax.spines[spine].set_visible(False)
    for spine in ('left', 'bottom'):
        ax.spines[spine].set_color('#7b8490')


    for ratio, note in ((0.3, None), (1.0, None), (3.0, None)):
        xs = np.array([0, 200])
        ax.plot(xs, xs / ratio, color=GREY, linewidth=0.5, linestyle=':',
                zorder=1)

    for row in rows:
        x = float(row['interruptions'])
        y = float(row['safe_completions'])
        name = row['method']
        is_ours = name == 'StateWise'
        oracle = 'oracle' in name.lower()
        ax.scatter([x], [y], s=44 if is_ours else 26,
                   color=BLUE if is_ours else (GREY if oracle else ORANGE),
                   marker='D' if is_ours else ('s' if oracle else 'o'),
                   edgecolor='#111827' if is_ours else 'none',
                   linewidth=0.8, zorder=3)
        short = (name.replace(' memory (oracle)', ' mem*')
                 .replace(' memory', ' mem').replace(' approval', ' appr'))


        offsets = {
            'StateWise': (7, -2),
            'Correct memory (oracle)': (-8, 7),
            'MemLineage': (4, 4),
            'Corrupted memory': (-4, -10),
            'Ask-or-Assume': (4, 5),
            'No memory': (4, 4),
            'Clarification': (4, -9),
            'Safety Sentry': (-16, 7),
            'Rationale approval': (4, 4),
            'Bare approval': (4, -10),
        }
        dx, dy = offsets.get(name, (4, 4))
        ax.annotate(short, (x, y), textcoords='offset points',
                    xytext=(dx, dy), fontsize=5.6, color='#2d333b')
    ax.set_xlabel('Developer interruptions (150 episodes)', fontsize=7.4)
    ax.set_ylabel('Safe completions', fontsize=7.4)
    ax.set_xlim(-10, 205)
    ax.set_ylim(0, 172)
    ax.tick_params(labelsize=6.6)
    ax.text(138, 156, 'better', fontsize=6, color=GREY, style='italic')
    ax.annotate('', xy=(112, 164), xytext=(152, 150),
                arrowprops=dict(arrowstyle='->', color=GREY, linewidth=0.7))
    fig.subplots_adjust(left=0.14, right=0.99, top=0.97, bottom=0.16)
    save(fig, 'fig_humancost_efficiency')


def gate_curve() -> None:

    rows = sorted(read(CURVE / 'curve_points.csv'),
                  key=lambda r: int(r['threshold']))
    gated = [float(r['episodes_gated_pct']) for r in rows]
    completion = [float(r['completion_pct']) for r in rows]
    violation = [float(r['violation_pct']) for r in rows]
    prompts = [float(r['prompts_per_episode']) for r in rows]
    thresholds = [int(r['threshold']) for r in rows]

    fig, axes = plt.subplots(1, 2, figsize=(6.9, 2.5))

    ax = axes[0]
    ax.grid(color='#d9dde3', linewidth=0.6)
    ax.set_axisbelow(True)
    for spine in ('top', 'right'):
        ax.spines[spine].set_visible(False)
    order = np.argsort(gated)
    ax.plot(np.array(gated)[order], np.array(completion)[order],
            color=BLUE, linewidth=1.1, marker='o', markersize=5, zorder=3)
    for t, g, c in zip(thresholds, gated, completion):
        default = ' (default)' if t == 2 else ''
        ax.annotate('t=%d%s' % (t, default), (g, c),
                    textcoords='offset points', xytext=(5, -9),
                    fontsize=6.2,
                    color='#111827' if t == 2 else '#2d333b',
                    fontweight='bold' if t == 2 else 'normal')
    ax.set_xlabel('Episodes requiring permission (%)', fontsize=7.4)
    ax.set_ylabel('Should-act completion (%)', fontsize=7.4)
    ax.set_ylim(0, 112)
    ax.set_xlim(-6, 112)
    ax.tick_params(labelsize=6.6)
    ax.set_title('Capability vs oversight cost', fontsize=8, color='#4b5563',
                 pad=4)

    ax = axes[1]
    ax.grid(axis='y', color='#d9dde3', linewidth=0.6)
    ax.set_axisbelow(True)
    for spine in ('top', 'right'):
        ax.spines[spine].set_visible(False)
    x = np.arange(len(rows))
    width = 0.26
    for i, (vals, color, label) in enumerate((
            (completion, BLUE, 'Completion'),
            (prompts, ORANGE, 'Prompts / episode'),
            (violation, GREEN, 'Safety violation'))):
        bars = ax.bar(x + (i - 1) * width, vals, width, color=color,
                      label=label)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, v + 1.5,
                    '%.1f' % v if v < 10 else '%.0f' % v,
                    ha='center', va='bottom', fontsize=5.6, color='#2d333b')
    ax.set_xticks(x, ['t=%d%s' % (t, '\n(default)' if t == 2 else '')
                      for t in thresholds])
    ax.tick_params(axis='x', labelsize=6.4)
    ax.tick_params(axis='y', labelsize=6.6)
    ax.set_ylim(0, 112)
    ax.set_ylabel('Rate (%) / count', fontsize=7.4)
    ax.legend(frameon=False, fontsize=6.2, loc='upper center',
              bbox_to_anchor=(0.5, 1.16), ncol=3, handlelength=1.2,
              columnspacing=0.8)
    fig.subplots_adjust(left=0.08, right=0.99, top=0.86, bottom=0.20,
                        wspace=0.28)
    save(fig, 'fig_gate_curve')


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
    humancost_scatter()
    gate_curve()
