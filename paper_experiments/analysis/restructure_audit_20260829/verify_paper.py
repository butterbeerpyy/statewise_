from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PAPER = REPO / 'paper/fse2027'
MAIN = PAPER / 'main.tex'
EVAL = PAPER / 'sections/evaluation.tex'
APPX = PAPER / 'sections/appendix.tex'
PROBLEM = PAPER / 'sections/problem.tex'
FULL = 'statewise_v2_contract_corrected_typedfix'

failures: list[str] = []
count = {'n': 0}


def check(label: str, ok: bool) -> None:
    count['n'] += 1
    if not ok:
        failures.append(label)


def contains(label: str, needle: str, text: str) -> None:


    norm_text = ' '.join(text.split())
    norm_needle = ' '.join(needle.split())
    check('%s (%s)' % (label, needle), norm_needle in norm_text)


def pct(rate: float) -> str:
    return '%.1f' % (float(rate) * 100)


def table_body(text: str, label: str) -> str:
    pattern = (r'\\begin\{table\*?\}\[[^]]*\](?:(?!\\end\{table\*?\}).)*?'
               r'\\label\{%s\}(?:(?!\\end\{table\*?\}).)*?'
               r'\\end\{table\*?\}') % re.escape(label)
    matches = list(re.finditer(pattern, text, re.DOTALL))
    assert len(matches) == 1, '%s matched %d' % (label, len(matches))
    return matches[0].group(0)


def main() -> int:
    mt = MAIN.read_text(encoding='utf-8')
    ev = EVAL.read_text(encoding='utf-8')
    ap = APPX.read_text(encoding='utf-8')
    pr = PROBLEM.read_text(encoding='utf-8')
    both = ev + '\n' + ap

    a = pd.read_csv(HERE / 'table_main_end_to_end.csv').set_index('arm')
    f = pd.read_csv(HERE / 'figure_deployment_frontier.csv').set_index('arm')
    b = pd.read_csv(HERE / 'table_component_localization.csv').set_index('variant')


    b_rates = pd.read_csv(
        REPO / 'paper_experiments/analysis/claim_evidence_20260823/rq4_component_matrix.csv'
    ).set_index('arm')
    b7 = pd.read_csv(HERE / 'table_component_appendix_7arm.csv').set_index('variant')
    c = pd.read_csv(HERE / 'table_longitudinal.csv').set_index('arm')
    cross = pd.read_excel(
        REPO / 'paper_experiments/analysis/rq1_rq4_crossmodel20_paper_data_FINAL.xlsx',
        sheet_name='Arm_Summary')
    cross = cross[
        cross.arm == 'statewise_v2_contract_corrected_typedfix'
    ].set_index('model')


    t1 = table_body(ev, 'tab:rq1')
    check('merged table declares Panel A', 'Panel A' in t1)
    check('merged table declares Panel B', 'Panel B' in t1)
    check('Panel A is attributed to RQ1', '(RQ1)' in t1)
    check('Panel B is attributed to RQ2', '(RQ2)' in t1)


    panel_a, panel_b = t1.split('\\emph{Panel B')
    base = a.loc['correct', 'safe_completion_rate'] * 100
    for arm in ('correct', 'corrupted', 'no_memory'):
        row = a.loc[arm]
        for rate in ('should_act_completion_rate', 'correct_stop_rate',
                     'safe_completion_rate', 'unsafe_action_rate'):
            contains('Panel A %s %s' % (arm, rate), pct(row[rate]), panel_a)
        if arm != 'correct':
            delta = row.safe_completion_rate * 100 - base
            contains('Panel A %s delta' % arm, '$-%.1f$' % abs(delta), panel_a)
    for label in ('Correct Memory', 'Corrupted Memory', 'No Memory'):
        contains('Panel A row label', label, panel_a)
    check('Panel A has exactly three conditions',
          len(re.findall(r'\n    (?:\\textbf\{)?(?:Correct|Corrupted|No) Memory',
                         panel_a)) == 3)
    check('Panel A excludes StateWise', 'StateWise' not in panel_a)
    check('Panel A carries Correct Stop', 'Correct' in panel_a
          and 'Stop' in panel_a)
    contains('T1 denominators in note', '125 cases', t1)
    contains('T1 denominators in note', 'Correct Stop over 25', t1)
    contains('T1 denominators in note', 'all 150', t1)
    contains('T1 paired stat', '95\\% CI $[-50.0, -34.0]$', t1)
    contains('T1 Holm p', '7.16', t1)
    contains('T1 title', 'Persistent-state corruption', t1)
    contains('T1 title includes action-level supervision',
             'action-level supervision', t1)
    check('T1 excludes per-episode cost metrics',
          'kTok' not in t1 and 'calls' not in t1.lower())


    for arm in ('corrupted', 'bare_approval', 'rationale_approval',
                'generic_clarification', 'safety_sentry'):
        row = a.loc[arm]
        for rate in ('should_act_completion_rate', 'safe_completion_rate',
                     'unsafe_action_rate', 'interaction_episodes_rate'):
            contains('Panel B %s %s' % (arm, rate), pct(row[rate]), panel_b)
    contains('Panel B includes Safety Sentry', 'Safety Sentry', panel_b)
    check('Panel B has five arms',
          len([line for line in panel_b.splitlines()
               if re.match(r'    (Corrupted Memory|Bare Approval'
                           r'|Rationale Approval|Clarification'
                           r'|Safety Sentry)', line)]) == 5)
    check('Panel B excludes StateWise', 'StateWise' not in panel_b)
    contains('Panel B carries Interaction Episodes', 'Interaction', panel_b)
    contains('T1 note on interactions',
             'state questions and permission prompts', t1)
    contains('T1 note on shared contract', 'shared by', t1)
    check('separate tab:rq2 removed', 'label{tab:rq2}' not in ev)
    check('no dangling tab:rq2 reference', 'ref{tab:rq2}' not in both)
    contains('RQ2 prose points at Panel B',
             'Panel~B of Table~\\ref{tab:rq1}', ev)
    contains('RQ1 prose points at Panel A',
             'Panel~A of Table~\\ref{tab:rq1}', ev)

    for name, text in (('problem.tex', pr), ('evaluation.tex', ev)):
        contains('%s RQ2 scope widened' % name,
                 'action-level safety routing', text)


    check('figure referenced', 'fig_deployment_frontier' in ev)
    contains('frontier caption direction', 'upper-left', ev)
    contains('frontier caption log gap', '12 missing logs', ev)
    for arm in f.index:
        row = f.loc[arm]
        check('figure carries %s' % arm,
              not pd.isna(row.panel_a_x_unsafe_action_pct)
              and not pd.isna(row.panel_b_x_interactions_per_100_episodes))
    check('figure has all ten arms', len(f) == 10)

    contains('RQ3 safe completions', '143/150', ev)
    contains('RQ3 safe pct', '95.3\\%', ev)
    contains('RQ3 unsafe', '0/150', ev)
    contains('RQ3 AoA safe', 'against 50', ev)
    contains('RQ3 incidence', '17.3\\% versus 20.7\\%', ev)
    contains('RQ3 mcnemar p', '0.3833', ev)
    contains('RQ3 I/SC statewise', '0.31', ev)
    contains('RQ3 I/SC aoa', '0.68', ev)
    contains('RQ3 reduction sentence', '54.8\\% fewer human interactions', ev)
    contains('RQ3 calls/SC', '18.0 calls', ev)
    contains('RQ3 ktok/SC', '12.1k tokens', ev)
    check('no total-interaction superiority claim',
          'fewer interactions than' not in ev
          and 'significantly fewer' not in ev.lower())
    check('no statistical-equivalence claim',
          'statistical equivalence' not in ev.lower()
          and 'statistically equivalent' not in ev.lower())


    t3 = table_body(ev, 'tab:rq4')
    for variant, row in b.iterrows():
        rate_row = b_rates.loc[variant]
        contains('T3 %s overall' % variant,
                 '%.1f' % rate_row.objective_correctness, t3)
        contains('T3 %s should-act' % variant,
                 '%.1f' % rate_row.action_completion, t3)
        if pd.isna(row.delta_vs_full_pp):
            continue
        contains('T3 %s disc' % variant,
                 '%d/%d' % (int(row.full_only_success),
                            int(row.variant_only_success)), t3)
        contains('T3 %s loss' % variant, '%.1f' % row.delta_vs_full_pp, t3)
        interval = '%.1f [%.1f, %.1f]' % (
            row.delta_vs_full_pp, row.paired_ci_low_pp,
            row.paired_ci_high_pp)
        check('main table %s omits CI' % variant, interval not in t3)
        mantissa = ('%.2e' % row.holm_adjusted_p).split('e')[0]
        contains('T3 %s holm' % variant, mantissa, t3)
    check('T3 Holm p is a column, not only a note',
          'Holm $p$ \\\\' in t3)
    contains('T3 title', 'Paired component ablation over 150 shared cases', t3)
    contains('T3 independent-run note',
             'independently executed paired run', t3)
    check('T3 defines overall correctness',
          'Overall' in t3 and 'objective correctness' in t3)
    contains('T3 declares Should-Act denominator', '125 cases', t3)
    check('T3 omits Safe metric label',
          re.search(r'\bSafe\b', t3) is None)
    for dropped in ('Attribution Correct', 'Resolution Correct',
                    'Repair Correct'):
        check('T3 omits %s' % dropped, dropped not in t3)
    check('T3 Holm family is six',
          'all 6 removals' in ' '.join(t3.split())
          or 'six' in t3.lower())


    tx = table_body(ev, 'tab:cross-model')
    model_labels = {
        'gpt-5.6-sol': 'GPT-5.6-sol',
        'deepseek-v4-pro': 'DeepSeek V4 Pro',
        'qwen3.7-max': 'Qwen 3.7 Max',
        'claude-fable-5': 'Claude Fable 5',
    }
    for model, label in model_labels.items():
        row = cross.loc[model]
        contains('cross-model label %s' % model, label, tx)
        for metric in ('behavioral_correctness_rate', 'action_completion_rate',
                       'safe_stop_rate', 'safety_violation_rate',
                       'repair_accuracy_rate'):
            contains('cross-model %s %s' % (model, metric),
                     pct(row[metric]), tx)
    contains('cross-model scope', 'frozen 20-case', tx)
    contains('cross-model Claude attrition',
             'two full-method provider responses remained empty', tx)
    check('cross-model table has no n column',
          not re.search(r'&\s*[$]?n[$]?\s*&', tx, re.IGNORECASE))
    check('cross-model table omits attribution F1',
          'Attribution' not in tx and 'F1' not in tx)


    t4 = table_body(ev, 'tab:rq5')
    for arm in c.index:
        row = c.loc[arm]
        for rate in ('t1_safe_task_rate', 'downstream_safe_tasks_rate',
                     'all_future_safe_rate'):
            contains('T4 %s %s' % (arm, rate), pct(row[rate]), t4)
        contains('T4 %s inter/seq' % arm,
                 '%.2f' % row.interactions_per_sequence, t4)

        contains('appendix %s ktok/seq retained' % arm,
                 '%.1f' % row.ktokens_per_sequence, ap)
        check('T4 %s per-sequence cost defined' % arm,
              str(row.interactions_per_sequence) != 'nan'
              and str(row.ktokens_per_sequence) != 'nan')
    check('T4 has eight arms', len(c) == 8)
    contains('T4 T1 column named for safe task', 'T1 Safe Task', t4)
    check('T4 does not say Safe Recovery', 'Safe Recovery' not in t4)
    contains('T4 Correct Memory disambiguated', 'Correct Memory', t4)
    check('T4 avoids the oracle suffix on correct memory',
          'Correct memory (oracle)' not in t4)
    contains('T4 title', 'Longitudinal reliability over 32 four-task', t4)
    contains('T4 points at the appendix for tokens',
             'appendixref{app:longitudinal-costs}', t4)
    contains('appendix longitudinal cost section exists',
             'label{app:longitudinal-costs}', ap)
    sw = c.loc[FULL]
    contains('T4 reuse', pct(sw.repaired_state_reuse_rate), t4)
    contains('T4 repeated intervention', pct(sw.repeated_intervention_rate), t4)
    contains('T4 I/successful', '%.2f' % sw.interactions_per_successful_sequence,
             t4)
    contains('T4 Q/successful', '%.2f' % sw.questions_per_successful_sequence,
             t4)
    contains('T4 AoA per-successful',
             '%.2f' % c.loc['ask_or_assume',
                            'interactions_per_successful_sequence'], t4)

    contains('RQ5 all-future', '29/32', ev)
    contains('RQ5 oracle', '30/32', ev)
    contains('RQ5 reuse prose', '97.9\\%', ev)
    contains('RQ5 repeated prose', '1.0\\%', ev)
    contains('RQ5 I/successful prose', '1.55', ev)
    contains('RQ5 Q/successful prose', '1.10', ev)


    for variant in ('w/o Replanning', 'w/o Residual Gate'):
        row = b7.loc[variant]
        contains('appendix %s' % variant, pct(row.safe_completion_rate), ap)
    for arm in a.index:
        contains('appendix cost %s' % arm,
                 '%.2f' % a.loc[arm, 'ktokens_per_safe'], ap)
    contains('appendix missing logs', '12 of 1500', ap)
    contains('gate section naming',
             'Residual-Gate Supervision-Cost Sensitivity', ap)
    check('gate not called a trade-off',
          'capability trade-off' not in ap)
    contains('answer policy fail-closed', '0/21', ap)
    contains('answer policy inconclusive', 'inconclusive', ap)


    main_tables = re.findall(r'\\label\{(tab:[a-z0-9-]+)\}', ev)
    check('exactly four main-text table floats', len(main_tables) == 4)
    check('table labels are rq1/rq4/cross-model/rq5',
          sorted(main_tables) ==
          ['tab:cross-model', 'tab:rq1', 'tab:rq4', 'tab:rq5'])

    check('every main-text table is single column',
          '\\begin{table*}' not in ev)
    check('the main-text figure is single column',
          '\\begin{figure*}' not in ev)
    main_figs = re.findall(r'\\label\{(fig:[a-z-]+)\}', ev)
    check('exactly one main-text results figure', len(main_figs) == 1)
    check('the results figure is the frontier', main_figs == ['fig:frontier'])
    check('appendix hidden from submission PDF',
          '\\newcommand{\\StateWiseAppendix}{}' in mt)
    check('hidden appendix is not directly input',
          '\\input{sections/appendix}' not in mt)
    for gone in ('tab:main', 'tab:rq3', 'tab:difficulty', 'tab:attention',
                 'fig:claim-memory-action', 'fig:claim-system-safeguards',
                 'fig:operator-robustness', 'fig:rq4-stratum'):
        check('removed float %s unreferenced' % gone,
              ('ref{%s}' % gone) not in both)
    for metric in ('Unnec.', 'unnecessary-mutation rate', 'Objective Correct'):
        check('dropped metric absent: %s' % metric, metric not in ev)
    check('7x150 not called independent cases',
          '1,050 cases' not in both and '1050 cases' not in both)

    check('no hard-coded table numbers',
          not re.search(r'Table~?[1-9]\b', ev))
    check('no hard-coded figure numbers',
          not re.search(r'Figure~?[1-9]\b', ev))


    for label in main_tables:
        body = table_body(ev, label)
        rows = [line for line in body.splitlines()
                if line.strip().endswith('\\\\')
                and '\\toprule' not in line and '\\midrule' not in line
                and 'multicolumn' not in line and 'cmidrule' not in line]
        joined = '\n'.join(rows)
        check('%s: no parenthesised rate cells' % label,
              not re.search(r'[0-9] \([0-9]+\.[0-9]\\%\)', joined))
        check('%s: no n= marker in body' % label, 'n{=}' not in body)
        check('%s: no $n$/N marker' % label, '$n$/' not in body)
    setup = ev.split('\\subsection{RQ1')[0]
    contains('setup states the case count', '150-case', setup)
    contains('setup states the should-act count', '125', setup)

    print('=' * 74)
    print('ARTIFACT->PAPER VERIFY: %d checks, %d failures'
          % (count['n'], len(failures)))
    print('=' * 74)
    for item in failures:
        print('  FAIL  %s' % item)
    if not failures:
        print('  every artifact value appears in its assigned display, and the')
        print('  five-display table structure + one results figure holds')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
