from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PRIMARY = REPO / 'paper_experiments/results/shared/permission_matched_v10_all_arms_20260819.xlsx'
RQ4 = REPO / 'paper_experiments/results/rq4/rq4_results.xlsx'
RQ4_SOURCE = Path('runs/formal_v10_rq4_ablations150_gpt56sol_20260822_r1'
                  r'\pilot_summary.json')
RQ5 = REPO / 'paper_experiments/results/rq5/rq5_results.xlsx'
CASES = REPO.parent / 'statewise/scaffold/experiments/w1_contract_corrected_v9/cases'

FULL = 'statewise_v2_contract_corrected_typedfix'
NAMES = {
    'correct': 'Correct memory',
    'corrupted': 'Corrupted memory',
    'no_memory': 'No memory',
    'bare_approval': 'Bare approval',
    'rationale_approval': 'Rationale approval',
    'generic_clarification': 'Clarification',
    'memlineage_trust': 'MemLineage',
    'safety_sentry': 'Safety Sentry',
    'ask_or_assume': 'Ask-or-Assume',
    FULL: 'StateWise',
}
ORDER = [NAMES[a] for a in
         ('correct', 'corrupted', 'no_memory', 'bare_approval',
          'rationale_approval', 'generic_clarification', 'memlineage_trust',
          'safety_sentry', 'ask_or_assume', FULL)]


OPS = ['WRONG_VALUE', 'STALE_VALUE', 'OVER_GENERALIZATION',
       'JOINT_POLICY_COLLAPSE', 'IMPLICIT_CONFLICT', 'SCOPE_MISMATCH']
OP_LABEL = {
    'WRONG_VALUE': 'Wrong value',
    'STALE_VALUE': 'Stale value',
    'OVER_GENERALIZATION': 'Over-generalization',
    'JOINT_POLICY_COLLAPSE': 'Joint policy collapse',
    'IMPLICIT_CONFLICT': 'Implicit conflict',
    'SCOPE_MISMATCH': 'Scope mismatch',
}
SEED = 20260827


def gate() -> None:
    r = subprocess.run([sys.executable, str(HERE / 'canary.py')],
                       cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        raise SystemExit('canary failed -- refusing to emit new numbers')
    print(r.stdout.strip().splitlines()[-1])


def case_design() -> pd.DataFrame:
    rows = {}
    for f in sorted(CASES.glob('*.json')):
        d = json.loads(f.read_text(encoding='utf-8'))
        diff = d.get('difficulty') or {}
        rows[d['case_id']] = {
            'operator': d['corruption_operator'],
            'observability': diff['observability'],
            'causal_depth': diff['causal_depth'],
            'impact': diff['impact'],
            'persistence': diff['persistence'],
        }
    m = pd.DataFrame.from_dict(rows, orient='index')
    m.index.name = 'case_id'
    return m


def stratum_of(case_id: str, domain: str) -> str:
    if 'core_repo_state_environment_dependency' in case_id:
        return 'runtime'
    if domain == 'git_state':
        return 'git'
    return 'workspace'


def primary() -> pd.DataFrame:
    ep = pd.ExcelFile(PRIMARY).parse('Combined_Episodes')
    design = case_design()


    ep = ep.merge(design[['operator']], left_on='case_id', right_index=True,
                  how='left')
    assert ep.operator.notna().all(), 'unmatched case in design merge'
    for col in ('observability', 'causal_depth', 'impact', 'persistence'):
        got = ep.set_index('case_id')[col]
        want = design[col].reindex(got.index)
        assert (got.values == want.values).all(), \
            'workbook %s disagrees with the frozen case files' % col
    ep['stratum'] = [stratum_of(str(c), str(d))
                     for c, d in zip(ep.case_id, ep.domain)]
    ep['method'] = ep.arm.map(NAMES)
    return ep


def exact_mcnemar(a: np.ndarray, b: np.ndarray) -> tuple[int, int, float]:

    from math import comb
    a_only = int(np.sum(a & ~b))
    b_only = int(np.sum(b & ~a))
    n = a_only + b_only
    if n == 0:
        return a_only, b_only, 1.0
    k = min(a_only, b_only)
    tail = sum(comb(n, i) for i in range(k + 1)) / (2 ** n)
    return a_only, b_only, min(1.0, 2 * tail)


def paired_ci(a: np.ndarray, b: np.ndarray, iters: int = 10000
              ) -> tuple[float, float]:
    rng = np.random.default_rng(SEED)
    n = len(a)
    diffs = np.empty(iters)
    for i in range(iters):
        idx = rng.integers(0, n, n)
        diffs[i] = a[idx].mean() - b[idx].mean()
    return float(np.percentile(diffs, 2.5)) * 100, float(np.percentile(diffs, 97.5)) * 100


def holm(pvals: dict[str, float]) -> dict[str, float]:
    ordered = sorted(pvals, key=lambda k: pvals[k])
    out, running, total = {}, 0.0, len(ordered)
    for rank, key in enumerate(ordered):
        running = max(running, min(1.0, (total - rank) * pvals[key]))
        out[key] = running
    return out


def build_operator(ep: pd.DataFrame) -> None:

    rows = []
    for op in OPS:
        sub = ep[ep.operator == op]
        n = sub.case_id.nunique()
        row = {'operator': OP_LABEL[op], 'raw_operator': op, 'cases': n}
        for arm, name in NAMES.items():
            s = sub[sub.arm == arm]
            row['%s_obj' % name] = round(s.behaviorally_correct.mean() * 100, 1)
            row['%s_viol' % name] = round(s.safety_violation.mean() * 100, 1)
        rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(HERE / 'operator_matrix.csv', index=False)
    print('\n== A1 per-operator objective correctness')
    print(df[['operator', 'cases'] +
             ['%s_obj' % n for n in ('Corrupted memory', 'Rationale approval',
                                     'Safety Sentry', 'MemLineage',
                                     'Correct memory', 'StateWise')]]
          .to_string(index=False))


    prows, praw = [], {}
    for op in OPS:
        sub = ep[ep.operator == op]
        piv = sub.pivot_table(index='case_id', columns='arm',
                              values='behaviorally_correct')
        a = piv[FULL].to_numpy(dtype=bool)
        b = piv['corrupted'].to_numpy(dtype=bool)
        ao, bo, p = exact_mcnemar(a, b)
        lo, hi = paired_ci(a.astype(float), b.astype(float))
        praw[op] = p
        prows.append({'operator': OP_LABEL[op], 'raw_operator': op,
                      'cases': len(a),
                      'statewise': round(a.mean() * 100, 1),
                      'corrupted': round(b.mean() * 100, 1),
                      'difference': round((a.mean() - b.mean()) * 100, 1),
                      'ci_low': round(lo, 1), 'ci_high': round(hi, 1),
                      'statewise_only': ao, 'corrupted_only': bo,
                      'mcnemar_p': p})
    adj = holm(praw)
    for r in prows:
        r['holm_p'] = adj[r['raw_operator']]
    pdf = pd.DataFrame(prows)
    pdf.to_csv(HERE / 'operator_paired.csv', index=False)
    print('\n== A1 paired StateWise vs corrupted, per operator')
    print(pdf[['operator', 'cases', 'statewise', 'corrupted', 'difference',
               'ci_low', 'ci_high', 'holm_p']].to_string(index=False))


def build_severity(ep: pd.DataFrame) -> None:

    rows = []
    for arm, name in NAMES.items():
        s = ep[ep.arm == arm]
        row = {'method': name}
        for tier in ('I2', 'I3', 'I4'):
            t = s[s.impact == tier]
            row['%s_viol' % tier] = round(t.safety_violation.mean() * 100, 1)
            row['%s_unnec' % tier] = round(
                t.unnecessary_mutation_rate.mean() * 100, 1)
        rows.append(row)
    df = pd.DataFrame(rows).set_index('method').reindex(ORDER).reset_index()
    df.to_csv(HERE / 'severity_matrix.csv', index=False)
    counts = {t: int((ep[ep.arm == 'corrupted'].impact == t).sum())
              for t in ('I2', 'I3', 'I4')}
    print('\n== A2 violation / unnecessary mutation by impact tier  %s' % counts)
    print(df.to_string(index=False))


def build_depth(ep: pd.DataFrame) -> None:

    rows = []
    for arm, name in NAMES.items():
        s = ep[ep.arm == arm]
        row = {'method': name}
        for d in ('D2', 'D3', 'D4'):
            row[d] = round(s[s.causal_depth == d].behaviorally_correct.mean()
                           * 100, 1)
        row['D4_minus_D2'] = round(row['D4'] - row['D2'], 1)
        rows.append(row)
    df = pd.DataFrame(rows).set_index('method').reindex(ORDER).reset_index()
    df.to_csv(HERE / 'depth_matrix.csv', index=False)
    counts = {d: int((ep[ep.arm == 'corrupted'].causal_depth == d).sum())
              for d in ('D2', 'D3', 'D4')}
    print('\n== A3 correctness by causal depth  %s' % counts)
    print(df.to_string(index=False))


def build_rq4_stratum() -> None:

    payload = json.loads(RQ4_SOURCE.read_text(encoding='utf-8'))
    rec = pd.DataFrame(payload['records'])

    rec['objective'] = ((rec.risk_adjusted_task_success.astype(bool)
                         | rec.acceptable_safe_terminal.astype(bool))
                        & ~rec.safety_violation.astype(bool))
    design = case_design()
    rec = rec.merge(design[['operator']], left_on='case_id', right_index=True,
                    how='left')
    assert rec.operator.notna().all(), 'unmatched RQ4 case'
    dom = (pd.ExcelFile(RQ4).parse('Episode_Data')
           .drop_duplicates('case_id').set_index('case_id')['domain'])
    rec['domain'] = rec.case_id.map(dom)
    rec['stratum'] = [stratum_of(str(c), str(d))
                      for c, d in zip(rec.case_id, rec.domain)]

    label = {
        FULL: 'Full StateWise',
        'statewise_ablation_no_attribution': 'w/o Attribution',
        'statewise_ablation_no_resolution': 'w/o Resolution',
        'statewise_ablation_no_repair': 'w/o Persistent Repair',
        'statewise_ablation_no_typed_grounding': 'w/o Typed Grounding',
    }
    rows = []
    for arm, name in label.items():
        s = rec[rec.arm == arm]
        row = {'arm': name, 'overall': round(s.objective.mean() * 100, 1)}
        for st in ('runtime', 'workspace', 'git'):
            row[st] = round(s[s.stratum == st].objective.mean() * 100, 1)
        rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(HERE / 'rq4_stratum.csv', index=False)
    if abs(df.loc[df.arm == 'Full StateWise', 'overall'].iloc[0] - 93.3) > 0.05:
        raise SystemExit('RQ4 anchor no longer reproduces the paper 93.3')
    print('\n== A5 RQ4 ablations by state stratum (paper-anchored scoring)')
    print(df.to_string(index=False))


    rows = []
    for arm, name in label.items():
        s = rec[rec.arm == arm]
        row = {'arm': name}
        for op in OPS:
            row[OP_LABEL[op]] = round(s[s.operator == op].objective.mean()
                                      * 100, 1)
        rows.append(row)
    op_df = pd.DataFrame(rows)
    op_df.to_csv(HERE / 'rq4_operator.csv', index=False)
    print('\n== A5b RQ4 ablations by corruption operator')
    print(op_df.to_string(index=False))


def build_rq5_attention() -> None:

    x = pd.ExcelFile(RQ5)
    seq = x.parse('Sequence_Data')
    seq = seq[seq.primary_in_scope == True]
    td = x.parse('Task_Data')
    prov = x.parse('Run_Provenance')
    keep = {FULL: 'StateWise', 'correct': 'Correct memory (oracle)',
            'memlineage_trust': 'MemLineage', 'safety_sentry': 'Safety Sentry',
            'ask_or_assume': 'Ask-or-Assume'}
    rows = []
    for arm, name in keep.items():
        s = seq[seq.arm == arm]
        t = td[td.arm == arm]
        p = prov[prov.arm == arm]
        strict = ((s.future_task_success_rate >= 1.0)
                  & (s.cumulative_safety_violations == 0)).mean() * 100
        rows.append({
            'method': name,
            'sequences': len(s),
            'strict': round(strict, 1),
            'questions_per_seq': round(s.cumulative_questions.mean(), 2),
            'permissions_per_seq': round(
                s.cumulative_permission_interactions.mean(), 2),
            'permissions_max': int(s.cumulative_permission_interactions.max()),
            'interactions_per_seq': round(
                (s.cumulative_questions
                 + s.cumulative_permission_interactions).mean(), 2),
            'repeated_intervention': round(s.repeated_intervention_rate.mean()
                                           * 100, 1),
            'calls_per_task': round(p.calls.sum() / len(t), 1),
        })
    df = pd.DataFrame(rows)
    df.to_csv(HERE / 'rq5_attention.csv', index=False)
    print('\n== A4 developer-attention cost per four-task sequence')
    print(df.to_string(index=False))


def main() -> None:
    gate()
    ep = primary()
    build_operator(ep)
    build_severity(ep)
    build_depth(ep)
    build_rq4_stratum()
    build_rq5_attention()
    print('\nwrote CSVs to %s' % HERE)


if __name__ == '__main__':
    main()
