from __future__ import annotations

from pathlib import Path

import pandas as pd

pd.set_option('display.width', 200)
H = Path(__file__).resolve().parent
REPO = H.parents[2]
a = pd.read_csv(H / 'table_main_end_to_end.csv').set_index('arm')
b = pd.read_csv(H / 'table_component_localization.csv').set_index('variant')
c = pd.read_csv(H / 'table_longitudinal.csv').set_index('arm')
FULL = 'statewise_v2_contract_corrected_typedfix'


def pct(rate: float) -> str:
    return '%.1f' % (float(rate) * 100)


def sci(p: float) -> str:

    mantissa, exponent = ('%.2e' % float(p)).split('e')
    exponent = int(exponent)
    return '%s\\!\\times\\!10^{%d}' % (mantissa, exponent)


def table_one() -> str:

    base = a.loc['correct', 'safe_completion_rate'] * 100
    lines = [
        '\\begin{table}[!tb]',
        '  \\caption{Persistent-State Corruption and Action-Level Supervision.',
        '  \\textbf{Panel A} isolates the corruption: it costs 42.0 points of',
        '  safe completion and produces forbidden mutations, and deleting the',
        '  record is safer but recovers less than half the objectives.',
        '  \\textbf{Panel B} asks whether supervising the action recovers the',
        '  task: approval drives unsafe actions to zero yet leaves safe',
        '  completion at the corrupted control\'s level while interrupting the',
        '  developer in four episodes out of five. All rates are percentages.}',
        '  \\label{tab:rq1}',
        '  \\centering\\small',

        '  \\begin{tabular*}{\\columnwidth}{@{\\extracolsep{\\fill}}lrrrrr@{}}',
        '    \\multicolumn{6}{@{}l}{\\emph{Panel A: effect of corrupting one'
        ' record (RQ1)}} \\\\',
        '    \\toprule',
        '    Memory & Should-Act & Correct & Safe & Unsafe & $\\Delta$ vs \\\\',
        '    Condition & Compl. & Stop & Compl. & Action & Correct \\\\',
        '    \\midrule',
    ]
    for arm in ('correct', 'corrupted', 'no_memory'):
        row = a.loc[arm]
        delta_pp = row.safe_completion_rate * 100 - base
        delta = ('---' if arm == 'correct'
                 else '$%s%.1f$' % ('' if delta_pp >= 0 else '-', abs(delta_pp)))
        cells = [pct(row.should_act_completion_rate),
                 pct(row.correct_stop_rate),
                 pct(row.safe_completion_rate),
                 pct(row.unsafe_action_rate)]
        name = {'correct': 'Correct Memory', 'corrupted': 'Corrupted Memory',
                'no_memory': 'No Memory'}[arm]
        if arm == 'correct':
            name = '\\textbf{%s}' % name
            cells = ['\\textbf{%s}' % v for v in cells]
        lines.append('    %s & %s & %s \\\\'
                     % (name, ' & '.join(cells), delta))
    lines += [
        '    \\bottomrule',
        '  \\end{tabular*}',
        '  \\vspace{4pt}',

        '  \\begin{tabular*}{\\columnwidth}{@{\\extracolsep{\\fill}}lrrrr@{}}',
        '    \\multicolumn{5}{@{}l}{\\emph{Panel B: action-level supervision'
        ' (RQ2)}} \\\\',
        '    \\toprule',
        '    & Should-Act & Safe & Unsafe & Interaction \\\\',
        '    Method & Compl. & Compl. & Action & Episodes \\\\',
        '    \\midrule',
    ]
    labels = {'corrupted': 'Corrupted Memory', 'bare_approval': 'Bare Approval',
              'rationale_approval': 'Rationale Approval',
              'generic_clarification': 'Clarification',
              'safety_sentry': 'Safety Sentry'}
    for arm in ('corrupted', 'bare_approval', 'rationale_approval',
                'generic_clarification', 'safety_sentry'):
        row = a.loc[arm]
        cells = [pct(row.should_act_completion_rate),
                 pct(row.safe_completion_rate),
                 pct(row.unsafe_action_rate),
                 pct(row.interaction_episodes_rate)]
        lines.append('    %s & %s \\\\' % (labels[arm], ' & '.join(cells)))
    lines += [
        '    \\bottomrule',
        '  \\end{tabular*}',
        '  \\parbox{\\columnwidth}{\\footnotesize\\vspace{2pt}',
        '  Should-Act Completion is over 125 cases, Correct Stop over 25, and',
        '  the remaining rates over all 150. $\\Delta$ is in percentage points',
        '  against Correct Memory; negative values are losses. Interactions',
        '  include state questions and permission prompts, and the corrupted',
        '  control receives them only through the permission contract shared by',
        '  all arms. Panel A: Correct vs. Corrupted paired safe-completion',
        '  difference $-42.0$ pp, 95\\% CI $[-50.0, -34.0]$, Holm-adjusted',
        '  $p{=}7.16\\!\\times\\!10^{-18}$.}',
        '\\end{table}',
    ]
    return '\n'.join(lines) + '\n'


def table_three() -> str:

    lines = [
        '\\begin{table}[!tb]',
        '  \\caption{Paired Component Ablation over 150 Shared Cases.',
        '  \\emph{Disc.}\\ gives the McNemar discordant pairs as',
        '  Full-only\\,/\\,variant-only. \\emph{Loss} is Full minus variant in',
        '  percentage points. Removing any of the four mechanisms costs a',
        '  large, significant share of safe completion.}',
        '  \\label{tab:rq4}',
        '  \\centering\\small',
        '  \\begin{tabular*}{\\columnwidth}{@{\\extracolsep{\\fill}}lrcrl@{}}',
        '    \\toprule',
        '    Variant & Safe & Disc. & Loss & Holm $p$ \\\\',
        '    \\midrule',
    ]
    for variant, row in b.iterrows():
        safe = pct(row.safe_completion_rate)
        if pd.isna(row.delta_vs_full_pp):
            lines.append('    \\textbf{%s} & \\textbf{%s} & --- & --- & --- \\\\'
                         % (variant, safe))
            lines.append('    \\midrule')
            continue
        disc = '%d/%d' % (int(row.full_only_success),
                          int(row.variant_only_success))
        loss = '%.1f' % row.delta_vs_full_pp
        holm = '$%s$' % sci(row.holm_adjusted_p)
        lines.append('    %s & %s & %s & %s & %s \\\\'
                     % (variant, safe, disc, loss, holm))
    family = int(b.holm_family_size.dropna().iloc[0])
    lines += [
        '    \\bottomrule',
        '  \\end{tabular*}',
        '  \\parbox{\\columnwidth}{\\footnotesize\\vspace{2pt}',
        '  Safe completion is a percentage; loss is in percentage points, and a',
        '  positive loss means removing the component degrades the outcome.',
        '  Paired-bootstrap 95\\% intervals for every removal appear in',
        '  \\appendixref{app:rq4-exploratory}. Holm correction spans all %d'
        % family,
        '  removals actually executed, including the two reported only in that',
        '  appendix, so the displayed subset does not gain significance from a',
        '  smaller family. RQ4 is an independently executed paired run: its Full',
        '  reference achieved %s\\%%, whereas the headline \\statewise{} run used'
        % pct(b.iloc[0].safe_completion_rate),
        '  for RQ3 achieved %s\\%%.}' % pct(a.loc[FULL, 'safe_completion_rate']),
        '\\end{table}',
    ]
    return '\n'.join(lines) + '\n'


def table_four() -> str:

    order = ['correct', 'corrupted', 'no_memory', 'memlineage_trust',
             'safety_sentry', 'ask_or_assume', 'oracle_statewise', FULL]
    lines = [
        '\\begin{table}[!tb]',
        '  \\caption{Longitudinal Reliability over 32 Four-Task Sequences (128',
        '  tasks per method). \\emph{All-Future} requires every task after the',
        '  first to complete without violating the sequence invariant.',
        '  Interactions use a per-sequence denominator, so every cell is',
        '  defined. Outcome columns are percentages.}',
        '  \\label{tab:rq5}',
        '  \\centering\\small',
        '  \\begin{tabular*}{\\columnwidth}{@{\\extracolsep{\\fill}}lrrrr@{}}',
        '    \\toprule',
        '    & \\multicolumn{3}{c}{Safe outcomes (\\%)} & Inter. \\\\',
        '    \\cmidrule(r){2-4}\\cmidrule(l){5-5}',
        '    Method & T1 Safe & T2--T4 Safe & All-Future & Inter. \\\\',
        '    & Task & Tasks & Sequences & / seq. \\\\',
        '    \\midrule',
    ]
    for arm in order:
        row = c.loc[arm]
        cells = [pct(row.t1_safe_task_rate),
                 pct(row.downstream_safe_tasks_rate),
                 pct(row.all_future_safe_rate),
                 '%.2f' % row.interactions_per_sequence]
        if arm == FULL:
            cells = ['\\textbf{%s}' % v for v in cells[:3]] + cells[3:]


        name = {'correct': 'Correct Memory',
                'corrupted': 'Corrupted Memory',
                'no_memory': 'No Memory',
                'memlineage_trust': 'MemLineage',
                'safety_sentry': 'Safety Sentry',
                'ask_or_assume': 'Ask-or-Assume',
                'oracle_statewise': 'Oracle StateWise$^{\\dagger}$',
                FULL: '\\textbf{StateWise}'}[arm]
        lines.append('    %s & %s \\\\' % (name, ' & '.join(cells)))
    sw = c.loc[FULL]
    lines += [
        '    \\bottomrule',
        '  \\end{tabular*}',
        '  \\parbox{\\columnwidth}{\\footnotesize\\vspace{2pt}',
        '  T1 Safe Task requires task~1 to satisfy its oracle without a safety',
        '  violation; it is over 32 sequences, T2--T4 Safe Tasks over 96',
        '  downstream tasks, and All-Future Sequences over 32 sequences.',
        '  Per-sequence token cost is in',
        '  \\appendixref{app:longitudinal-costs}.',
        '  $^{\\dagger}$Non-deployable diagnostic: it receives the annotated',
        '  support set directly. \\statewise{} reuses the repaired record in',
        '  %s\\%% of downstream planner contexts and re-interrogates the'
        % pct(sw.repaired_state_reuse_rate),
        '  developer in %s\\%% of sequences; per successful sequence it spends'
        % pct(sw.repeated_intervention_rate),
        '  %.2f interactions, of which %.2f are state questions.'
        % (sw.interactions_per_successful_sequence,
           sw.questions_per_successful_sequence),
        '  Ask-or-Assume spends %.2f interactions per sequence but converts them'
        % c.loc['ask_or_assume', 'interactions_per_sequence'],
        '  into a single success, i.e.\\ %.2f interactions per successful'
        % c.loc['ask_or_assume', 'interactions_per_successful_sequence'],
        '  sequence.}',
        '\\end{table}',
    ]
    return '\n'.join(lines) + '\n'


def appendix_longitudinal_costs() -> str:
    order = ['correct', 'corrupted', 'no_memory', 'memlineage_trust',
             'safety_sentry', 'ask_or_assume', 'oracle_statewise', FULL]
    lines = [
        '\\begin{table}[t]',
        '  \\caption{Per-sequence inference cost in the longitudinal pool, and',
        '  the same interaction counts normalized by successful sequence. The',
        '  per-successful-sequence columns are undefined for the four arms that',
        '  never reach the all-future endpoint.}',
        '  \\label{tab:longitudinal-costs}',
        '  \\centering\\small',
        '  \\begin{tabular*}{\\columnwidth}{@{\\extracolsep{\\fill}}lrrrr@{}}',
        '    \\toprule',
        '    & \\multicolumn{2}{c}{Per sequence}'
        ' & \\multicolumn{2}{c}{Per successful sequence} \\\\',
        '    \\cmidrule(r){2-3}\\cmidrule(l){4-5}',
        '    Method & Inter. & kTokens & Inter. & kTokens \\\\',
        '    \\midrule',
    ]
    labels = {'correct': 'Correct Memory', 'corrupted': 'Corrupted Memory',
              'no_memory': 'No Memory', 'memlineage_trust': 'MemLineage',
              'safety_sentry': 'Safety Sentry',
              'ask_or_assume': 'Ask-or-Assume',
              'oracle_statewise': 'Oracle StateWise', FULL: 'StateWise'}
    for arm in order:
        row = c.loc[arm]
        succ_i = row.interactions_per_successful_sequence
        succ_k = row.ktokens_per_successful_sequence
        lines.append('    %s & %.2f & %.1f & %s & %s \\\\'
                     % (labels[arm], row.interactions_per_sequence,
                        row.ktokens_per_sequence,
                        '---' if pd.isna(succ_i) else '%.2f' % succ_i,
                        '---' if pd.isna(succ_k) else '%.1f' % succ_k))
    lines += [
        '    \\bottomrule',
        '  \\end{tabular*}',
        '\\end{table}',
    ]
    return '\n'.join(lines) + '\n'


def main() -> None:
    LATEX = H / 'latex'
    LATEX.mkdir(exist_ok=True)

    for name, fn in [('table1_rq1.tex', table_one),
                     ('table3_rq4.tex', table_three),
                     ('table4_rq5.tex', table_four),
                     ('appendix_longitudinal_costs.tex',
                      appendix_longitudinal_costs)]:
        body = fn()
        (LATEX / name).write_text(body, encoding='utf-8')
        print('wrote %s' % name)


if __name__ == '__main__':
    main()
