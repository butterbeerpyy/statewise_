from __future__ import annotations

from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / 'latex'
OUT.mkdir(exist_ok=True)
FULL = 'statewise_v2_contract_corrected_typedfix'


def pct(rate: float) -> str:

    return '%.1f' % (float(rate) * 100)


def frac(num, den) -> str:
    return '%d/%d' % (int(num), int(den))


def cell(num, den, rate) -> str:

    return '%s (%s\\%%)' % (frac(num, den), pct(rate))


def cell_pct_only(num, den, rate) -> str:

    return '%s\\%%' % pct(rate)


def sci(value: float) -> str:

    text = '%.2e' % float(value)
    mantissa, exponent = text.split('e')
    return '%s\\!\\times\\!10^{%d}' % (mantissa, int(exponent))


a = pd.read_csv(HERE / 'table_main_end_to_end.csv').set_index('arm')
b = pd.read_csv(HERE / 'table_component_localization.csv')
b_app = pd.read_csv(HERE / 'table_component_appendix_7arm.csv')
c = pd.read_csv(HERE / 'table_longitudinal.csv').set_index('arm')


def table_one() -> str:

    groups = [
        ('Memory controls', ['correct', 'corrupted', 'no_memory']),
        ('Action-level supervision',
         ['bare_approval', 'rationale_approval', 'generic_clarification']),
        ('External systems',
         ['memlineage_trust', 'safety_sentry', 'ask_or_assume']),
        (None, [FULL]),
    ]
    lines = [
        '\\begin{table}[t]',
        '  \\caption{End-to-end outcomes on the frozen evaluation set. RQ1 is the',
        '  first block: corrupting one record costs 42.0 points of safe',
        '  completion and produces forbidden mutations, and deleting the record',
        '  is safer but recovers less than half the objectives. RQ2 is the second',
        '  block, and RQ3 compares the remaining arms against \\statewise{}.',
        '  \\emph{Interactions} counts state questions and permission prompts;',
        '  \\emph{per SC} normalizes by safe completion. All rates are',
        '  percentages.}',
        '  \\label{tab:rq1}',
        '  \\centering\\small',
        '  \\begin{tabular*}{\\columnwidth}'
        '{@{\\extracolsep{\\fill}}lrrrrr@{}}',
        '    \\toprule',
        '    & \\multicolumn{3}{c}{Outcome}'
        ' & \\multicolumn{2}{c}{Interactions} \\\\',
        '    \\cmidrule(r){2-4}\\cmidrule(l){5-6}',
        '    Approach & Compl. & Safe & Unsafe & Episodes & per SC \\\\',
        '    \\midrule',
    ]
    for group, arms in groups:
        if group:
            lines.append('    \\multicolumn{6}{@{}l}{\\emph{%s}} \\\\' % group)
        for arm in arms:
            row = a.loc[arm]
            cells = [pct(row.should_act_completion_rate),
                     pct(row.safe_completion_rate),
                     pct(row.unsafe_action_rate),
                     pct(row.interaction_episodes_rate),
                     '%.2f' % row.interactions_per_safe_zero_imputed]
            name = row.method
            if arm == FULL:
                name = '\\textbf{%s}' % name
                cells = ['\\textbf{%s}' % v for v in cells]
            lines.append('    %s & %s \\\\' % (name, ' & '.join(cells)))
        if group:
            lines.append('    \\addlinespace[2pt]')
    lines += [
        '    \\bottomrule',
        '  \\end{tabular*}',
        '  \\parbox{\\columnwidth}{\\footnotesize\\vspace{2pt}',
        '  Completion is conditioned on the \\textsc{should-act} cases; the other',
        '  rates use the whole set. The corrupted control records interactions',
        '  because every arm shares one permission contract, not because it',
        '  consults the developer. MemLineage never interrupts and still',
        '  completes only %s\\%%, so a low interaction count is not by itself an'
        % pct(a.loc['memlineage_trust', 'safe_completion_rate']),
        '  advantage. Per-arm inference cost is in'
        ' \\appendixref{app:full-costs}.}',
        '\\end{table}',
    ]
    return '\n'.join(lines) + '\n'


def table_two() -> str:
    arms = ['corrupted', 'bare_approval', 'rationale_approval',
            'generic_clarification']


    heads = ['Corrupt.', 'Bare', 'Ration.', 'Clarify']
    rows = [
        ('Safe completion', 'safe_completion_numerator',
         'safe_completion_denominator', 'safe_completion_rate'),
        ('Unsafe action', 'unsafe_action_numerator',
         'unsafe_action_denominator', 'unsafe_action_rate'),
        ('Episodes with interaction', 'interaction_episodes_numerator',
         'interaction_episodes_denominator', 'interaction_episodes_rate'),
    ]
    lines = [
        '\\begin{table}[t]',
        '  \\caption{RQ2: effectiveness and human cost of action-level',
        '  supervision. Approval eliminates unsafe actions but leaves safe',
        '  completion near the untreated control while interrupting the',
        '  developer in roughly four episodes out of five. Clarification obtains',
        '  an answer and still violates invariants, because the answer never',
        '  reaches the stored record. All cells are percentages over 150',
        '  episodes.}',
        '  \\label{tab:rq2}',
        '  \\centering\\small',
        '  \\begin{tabular*}{\\columnwidth}{@{\\extracolsep{\\fill}}lrrrr@{}}',
        '    \\toprule',
        '    Metric & %s \\\\' % ' & '.join(heads),
        '    \\midrule',
    ]
    for label, num, den, rate in rows:


        cells = [pct(a.loc[arm, rate]) for arm in arms]
        lines.append('    %s & %s \\\\' % (label, ' & '.join(cells)))
    lines += [
        '    \\bottomrule',
        '  \\end{tabular*}',
        '  \\parbox{\\columnwidth}{\\footnotesize\\vspace{2pt}',
        '  Columns are the corrupted-memory control, bare approval, rationale',
        '  approval, and clarification.',
        '  An interaction is a state question or a permission prompt. The',
        '  corrupted control records %s interactions because every arm shares one'
        % int(a.loc['corrupted', 'interactions_total_zero_imputed']),
        '  permission contract, not because it consults the developer. Action-time',
        '  routing and provenance systems are compared in',
        '  Figure~\\ref{fig:frontier}.}',
        '\\end{table}',
    ]
    return '\n'.join(lines) + '\n'


def table_three() -> str:
    lines = [
        '\\begin{table}[t]',
        '  \\caption{RQ4: paired one-component removal over 150 shared cases.',
        '  \\emph{Disc.}\\ gives the McNemar discordant pairs as',
        '  Full-only\\,/\\,variant-only. \\emph{Loss} is Full minus variant in',
        '  percentage points with a paired-bootstrap 95\\% interval. Removing any',
        '  of the four mechanisms costs a large, significant share of safe',
        '  completion.}',
        '  \\label{tab:rq4}',
        '  \\centering\\small',
        '  \\begin{tabular*}{\\columnwidth}'
        '{@{\\extracolsep{\\fill}}lrcr@{}}',
        '    \\toprule',
        '    Variant & Safe & Disc. & Loss [95\\% CI] (pp) \\\\',
        '    \\midrule',
    ]
    for _, row in b.iterrows():
        safe = pct(row.safe_completion_rate)
        if pd.isna(row.delta_vs_full_pp):
            lines.append('    \\textbf{%s} & \\textbf{%s} & --- & --- \\\\'
                         % (row.variant, safe))
            lines.append('    \\midrule')
            continue
        disc = '%d/%d' % (int(row.full_only_success),
                          int(row.variant_only_success))
        loss = '%.1f [%.1f, %.1f]' % (row.delta_vs_full_pp,
                                      row.paired_ci_low_pp,
                                      row.paired_ci_high_pp)
        lines.append('    %s & %s & %s & %s \\\\'
                     % (row.variant, safe, disc, loss))
    family = int(b.holm_family_size.dropna().iloc[0])
    holm_values = ', '.join(
        '%s $%s$' % (row.variant.replace('w/o ', ''), sci(row.holm_adjusted_p))
        for _, row in b.iterrows() if pd.notna(row.holm_adjusted_p))
    lines += [
        '    \\bottomrule',
        '  \\end{tabular*}',
        '  \\parbox{\\columnwidth}{\\footnotesize\\vspace{2pt}',
        '  A positive loss means removing the component degrades the outcome.',
        '  Holm-adjusted exact McNemar: %s.' % holm_values,
        '  Correction spans all %d removals actually executed, including the two'
        % family,
        '  reported only in \\appendixref{app:rq4-exploratory}, so the displayed',
        '  subset does not gain significance from a smaller family. This matrix',
        '  is an independently executed paired run, so its Full anchor is %s\\%%'
        % pct(b.iloc[0].safe_completion_rate),
        '  rather than the %s\\%% of the primary comparison.}'
        % pct(a.loc[FULL, 'safe_completion_rate']),
        '\\end{table}',
    ]
    return '\n'.join(lines) + '\n'


def table_four() -> str:
    order = ['correct', 'corrupted', 'no_memory', 'memlineage_trust',
             'safety_sentry', 'ask_or_assume', 'oracle_statewise', FULL]
    lines = [
        '\\begin{table}[t]',
        '  \\caption{RQ5: longitudinal reliability over 32 four-task sequences',
        '  (128 tasks per method). \\emph{All-fut.}\\ requires every task after',
        '  the first to complete without violating the sequence invariant.',
        '  Interaction and token costs use a per-sequence denominator, so every',
        '  cell is defined. Outcome columns are percentages over the denominator',
        '  in the header.}',
        '  \\label{tab:rq5}',
        '  \\centering\\small',
        '  \\begin{tabular*}{\\columnwidth}'
        '{@{\\extracolsep{\\fill}}lrrrrr@{}}',
        '    \\toprule',
        '    & \\multicolumn{3}{c}{Safe outcomes (\\%)}'
        ' & \\multicolumn{2}{c}{Per seq.} \\\\',
        '    \\cmidrule(r){2-4}\\cmidrule(l){5-6}',
        '    Method & T1 & T2--4 & All-fut. & Int. & kTok. \\\\',
        '    \\midrule',
    ]
    for arm in order:
        row = c.loc[arm]
        name = row.method


        t1 = pct(row.t1_safe_task_rate)
        later = pct(row.downstream_safe_tasks_rate)
        allf = pct(row.all_future_safe_rate)
        inter = '%.2f' % row.interactions_per_sequence
        ktok = '%.1f' % row.ktokens_per_sequence
        if arm == FULL:
            name = '\\textbf{%s}' % name
            t1, later, allf = ('\\textbf{%s}' % v for v in (t1, later, allf))
        if arm == 'oracle_statewise':
            name = '%s$^{\\dagger}$' % name
        lines.append('    %s & %s & %s & %s & %s & %s \\\\'
                     % (name, t1, later, allf, inter, ktok))
    sw = c.loc[FULL]
    lines += [
        '    \\bottomrule',
        '  \\end{tabular*}',
        '  \\parbox{\\columnwidth}{\\footnotesize\\vspace{2pt}',
        '  $^{\\dagger}$Non-deployable diagnostic: it receives the annotated',
        '  support set directly. \\statewise{} reuses the repaired record in',
        '  %s\\%% of downstream' % pct(sw.repaired_state_reuse_rate),
        '  planner contexts, and re-interrogates the developer in %s\\%% of'
        % pct(sw.repeated_intervention_rate),
        '  sequences; per successful sequence it spends %.2f interactions, of'
        % sw.interactions_per_successful_sequence,
        '  which %.2f are state questions.}'
        % sw.questions_per_successful_sequence,
        '\\end{table}',
    ]
    return '\n'.join(lines) + '\n'


def table_appendix() -> str:
    lines = [
        '\\begin{table*}[t]',
        '  \\caption{Complete seven-arm paired ablation, including the two',
        '  variants excluded from Table~\\ref{tab:rq4}. Safe completion is a',
        '  percentage over the 150 shared cases. Returning the corrected',
        '  context to the base planner and gating residual risk are execution',
        '  semantics rather than separately claimed recovery mechanisms; neither',
        '  removal produces a reliable difference.}',
        '  \\label{tab:rq4-exploratory}',
        '  \\centering\\small',
        '  \\begin{tabular*}{\\textwidth}{@{\\extracolsep{\\fill}}lccrl@{}}',
        '    \\toprule',
        '    Variant & Safe completion & Discordant'
        ' (Full\\,/\\,variant) & Loss [95\\% CI] & Holm $p$ \\\\',
        '    \\midrule',
    ]
    for _, row in b_app.iterrows():
        safe = pct(row.safe_completion_rate)
        if pd.isna(row.delta_vs_full_pp):
            lines.append('    \\textbf{%s} & \\textbf{%s} & --- & --- & --- \\\\'
                         % (row.variant, safe))
            lines.append('    \\midrule')
            continue
        disc = '%d\\,/\\,%d' % (int(row.full_only_success),
                               int(row.variant_only_success))
        loss = '%.1f [%.1f, %.1f]' % (row.delta_vs_full_pp,
                                      row.paired_ci_low_pp,
                                      row.paired_ci_high_pp)
        lines.append('    %s & %s & %s & %s & $%s$ \\\\'
                     % (row.variant, safe, disc, loss, sci(row.holm_adjusted_p)))
    lines += ['    \\bottomrule', '  \\end{tabular*}', '\\end{table*}']
    return '\n'.join(lines) + '\n'


def table_costs() -> str:
    order = ['correct', 'corrupted', 'no_memory', 'bare_approval',
             'rationale_approval', 'generic_clarification', 'memlineage_trust',
             'safety_sentry', 'ask_or_assume', FULL]
    lines = [
        '\\begin{table*}[t]',
        '  \\caption{Per-arm inference and interaction cost on the frozen',
        '  150-case set, normalized by safe completion. Cost is summed over',
        '  \\emph{all} episodes including failures, so an arm that fails cheaply',
        '  cannot appear efficient. \\emph{Avail.} recomputes the interaction',
        '  ratio over episodes whose interaction log survives.}',
        '  \\label{tab:full-costs}',
        '  \\centering\\small',
        '  \\begin{tabular*}{\\textwidth}'
        '{@{\\extracolsep{\\fill}}lrrrrr@{}}',
        '    \\toprule',
        '    Method & Quest. & Prompts & Inter./SC & Avail. & kTok./SC \\\\',
        '    \\midrule',
    ]
    for arm in order:
        row = a.loc[arm]
        avail = row.interactions_per_safe_available_case
        lines.append('    %s & %d & %d & %.2f & %s & %.2f \\\\'
                     % (row.method, int(row.questions_total),
                        int(row.permission_prompts_total),
                        row.interactions_per_safe_zero_imputed,
                        '%.2f' % avail if pd.notna(avail) else '---',
                        row.ktokens_per_safe))
    missing = int(a.missing_interaction_logs.sum())
    lines += [
        '    \\bottomrule',
        '  \\end{tabular*}',
        '  \\parbox{\\textwidth}{\\footnotesize\\vspace{2pt}',
        '  SC denotes a safe completion. %d of 1500 episodes lost their'
        % missing,
        '  interaction log when a recovery run directory was deleted',
        '  (clarification %d, bare approval %d); the main column imputes zero and'
        % (int(a.loc['generic_clarification', 'missing_interaction_logs']),
           int(a.loc['bare_approval', 'missing_interaction_logs'])),
        '  \\emph{Avail.} rescales the observed mean. The ordering is identical',
        '  under either rule.}',
        '\\end{table*}',
    ]
    return '\n'.join(lines) + '\n'


def main() -> None:
    outputs = {
        'table1_rq1.tex': table_one(),
        'table2_rq2.tex': table_two(),
        'table3_rq4.tex': table_three(),
        'table4_rq5.tex': table_four(),
        'appendix_rq4_7arm.tex': table_appendix(),
        'appendix_full_costs.tex': table_costs(),
    }
    for name, body in outputs.items():
        (OUT / name).write_text(body, encoding='utf-8')
        print('wrote latex/%s (%d lines)' % (name, body.count('\n')))
    print()
    print('=' * 72)
    print('sanity: every percentage is aa.a%')
    print('=' * 72)
    import re
    bad = []
    for name, body in outputs.items():
        for match in re.finditer(r'(\d+\.\d+)\\%', body):
            if len(match.group(1).split('.')[1]) != 1:
                bad.append((name, match.group(0)))
    print('non-one-decimal percentages: %d' % len(bad))
    for name, text in bad[:10]:
        print('  %s: %s' % (name, text))


if __name__ == '__main__':
    main()
