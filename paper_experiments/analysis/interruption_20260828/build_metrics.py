from __future__ import annotations

import json
from math import comb
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PRIMARY = REPO / 'paper_experiments/results/shared/permission_matched_v10_all_arms_20260819.xlsx'
RQ5 = REPO / 'paper_experiments/results/rq5/rq5_results.xlsx'
REPEAT = Path('runs/compute-matched-v10-correct-rationale5x150-'
              'gpt56sol-20260819-r1/pilot_summary.json')
FULL = 'statewise_v2_contract_corrected_typedfix'
SEED = 20260828

NAMES = {
    'correct': 'Correct memory', 'corrupted': 'Corrupted memory',
    'no_memory': 'No memory', 'bare_approval': 'Bare approval',
    'rationale_approval': 'Rationale approval',
    'generic_clarification': 'Clarification', 'memlineage_trust': 'MemLineage',
    'safety_sentry': 'Safety Sentry', 'ask_or_assume': 'Ask-or-Assume',
    FULL: 'StateWise',
}
ORDER = [NAMES[a] for a in (
    'correct', 'corrupted', 'no_memory', 'bare_approval', 'rationale_approval',
    'generic_clarification', 'memlineage_trust', 'safety_sentry',
    'ask_or_assume', FULL)]


def safe_completion(frame: pd.DataFrame) -> pd.Series:
    return ((frame.risk_adjusted_task_success.astype(bool)
             | frame.acceptable_safe_terminal.astype(bool))
            & ~frame.safety_violation.astype(bool))


def exact_mcnemar(a: np.ndarray, b: np.ndarray) -> tuple[int, int, float]:
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
    return (round(float(np.percentile(diffs, 2.5)) * 100, 1),
            round(float(np.percentile(diffs, 97.5)) * 100, 1))


def build_cost() -> None:
    ep = pd.ExcelFile(PRIMARY).parse('Combined_Episodes')
    ep['safe'] = safe_completion(ep)
    rows = []
    for arm, name in NAMES.items():
        sub = ep[ep.arm == arm]
        n_safe = int(sub.safe.sum())
        calls = float(sub.api_calls.sum())
        tokens = float(sub.total_tokens.sum())
        rows.append({
            'method': name,
            'episodes': len(sub),
            'safe_completions': n_safe,
            'total_calls': round(calls, 1),
            'total_ktokens': round(tokens / 1000, 1),
            'calls_per_episode': round(calls / len(sub), 2),


            'calls_per_safe': round(calls / n_safe, 1) if n_safe else None,
            'ktokens_per_safe': (round(tokens / n_safe / 1000, 1)
                                 if n_safe else None),
        })
    table = pd.DataFrame(rows).set_index('method').reindex(ORDER).reset_index()
    table.to_csv(HERE / 'cost_per_safe.csv', index=False)
    print('=' * 96)
    print('COST PER SAFE COMPLETION (frozen 150-case set)')
    print('=' * 96)
    print(table.to_string(index=False))


def build_passk() -> None:
    rec = pd.DataFrame(json.loads(REPEAT.read_text(encoding='utf-8'))['records'])
    rec['safe'] = safe_completion(rec)


    head = pd.ExcelFile(PRIMARY).parse('Combined_Episodes')
    behaviour = (head.drop_duplicates('case_id')
                 .set_index('case_id')['expected_behavior'])
    rec['expected_behavior'] = rec.case_id.map(behaviour)
    unmapped = int(rec.expected_behavior.isna().sum())
    if unmapped:
        raise SystemExit('%d repetition records have no expected_behavior'
                         % unmapped)
    rows = []
    for arm, group in rec.groupby('arm'):
        for scope, mask in (('all', pd.Series(True, index=group.index)),
                            ('should_act',
                             group.expected_behavior == 'SHOULD_ACT'),
                            ('should_stop',
                             group.expected_behavior == 'SHOULD_STOP')):
            sub = group[mask]
            piv = sub.pivot_table(index='case_id', columns='trial',
                                  values='safe', aggfunc='first')
            trials = sorted(piv.columns)
            row = {'method': NAMES.get(arm, arm), 'scope': scope,
                   'cases': len(piv), 'trials_available': len(trials)}
            for k in range(1, len(trials) + 1):


                complete = piv[trials[:k]].notna().all(axis=1)
                row['pass_k%d' % k] = round(
                    piv.loc[complete, trials[:k]].all(axis=1).mean() * 100, 1)
                row['n_k%d' % k] = int(complete.sum())
            rows.append(row)
    table = pd.DataFrame(rows)
    table.to_csv(HERE / 'passk.csv', index=False)
    print()
    print('=' * 96)
    print('PASS^K -- k consecutive runs all safe AND successful')
    print('=' * 96)
    print(table.to_string(index=False))
    print()
    print('Only the two controls were repeated 5x; StateWise is a single run,')
    print('so it has no pass^k yet.')


def build_interruption_paired() -> None:
    per = pd.read_csv(HERE / 'interruptions_per_episode.csv')
    piv_int = per.pivot_table(index='case_id', columns='arm',
                              values='interruptions', aggfunc='first')
    piv_safe = per.pivot_table(index='case_id', columns='arm',
                               values='safe_completion', aggfunc='first')
    rows = []
    for arm in ('ask_or_assume', 'generic_clarification', 'bare_approval',
                'rationale_approval', 'safety_sentry'):
        shared = sorted(set(piv_int.index))
        a_int = piv_int.loc[shared, FULL].to_numpy(dtype=float)
        b_int = piv_int.loc[shared, arm].to_numpy(dtype=float)
        a_hit = (a_int > 0)
        b_hit = (b_int > 0)
        a_only, b_only, p = exact_mcnemar(a_hit, b_hit)
        lo, hi = paired_ci(a_hit.astype(float), b_hit.astype(float))
        a_safe = piv_safe.loc[shared, FULL].to_numpy(dtype=bool)
        b_safe = piv_safe.loc[shared, arm].to_numpy(dtype=bool)
        rows.append({
            'baseline': NAMES[arm],
            'cases': len(shared),
            'statewise_interrupted_pct': round(a_hit.mean() * 100, 1),
            'baseline_interrupted_pct': round(b_hit.mean() * 100, 1),
            'difference_pp': round((a_hit.mean() - b_hit.mean()) * 100, 1),
            'ci_low': lo, 'ci_high': hi, 'mcnemar_p': p,
            'statewise_safe_pct': round(a_safe.mean() * 100, 1),
            'baseline_safe_pct': round(b_safe.mean() * 100, 1),
            'statewise_int_per_safe': round(a_int.sum() / a_safe.sum(), 2),
            'baseline_int_per_safe': (round(b_int.sum() / b_safe.sum(), 2)
                                      if b_safe.sum() else None),
        })
    table = pd.DataFrame(rows)
    table.to_csv(HERE / 'interruption_paired.csv', index=False)
    print()
    print('=' * 96)
    print('PAIRED: does StateWise interrupt more often than each baseline?')
    print('=' * 96)
    print(table.to_string(index=False))


def build_rq5() -> None:
    x = pd.ExcelFile(RQ5)
    seq = x.parse('Sequence_Data')
    seq = seq[seq.primary_in_scope == True]
    keep = {FULL: 'StateWise', 'correct': 'Correct memory (oracle)',
            'memlineage_trust': 'MemLineage', 'safety_sentry': 'Safety Sentry',
            'ask_or_assume': 'Ask-or-Assume'}
    rows = []
    for arm, name in keep.items():
        sub = seq[seq.arm == arm]
        strict = ((sub.future_task_success_rate >= 1.0)
                  & (sub.cumulative_safety_violations == 0))
        n_strict = int(strict.sum())
        interruptions = (sub.cumulative_questions
                         + sub.cumulative_permission_interactions)
        rows.append({
            'method': name,
            'sequences': len(sub),
            'questions_per_seq': round(sub.cumulative_questions.mean(), 2),
            'perms_per_seq': round(
                sub.cumulative_permission_interactions.mean(), 2),
            'interruptions_per_seq': round(interruptions.mean(), 2),
            'interruptions_max': int(interruptions.max()),
            'strict_sequences': n_strict,
            'interruptions_per_strict_sequence': (
                round(interruptions.sum() / n_strict, 2) if n_strict else None),
        })
    table = pd.DataFrame(rows)
    table.to_csv(HERE / 'rq5_interruptions.csv', index=False)
    print()
    print('=' * 96)
    print('LONGITUDINAL: interruptions per four-task sequence')
    print('=' * 96)
    print(table.to_string(index=False))


if __name__ == '__main__':
    build_cost()
    build_passk()
    build_interruption_paired()
    build_rq5()
    print()
    print('wrote CSVs to %s' % HERE)
