from __future__ import annotations

import argparse
import json
from math import comb
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
POOL = HERE / 'pool.json'
POLICIES = ('correct', 'unavailable', 'unknown', 'wrong', 'partial')
LABEL = {
    'correct': 'correct (control)',
    'unavailable': 'unavailable',
    'unknown': 'says "don\'t know"',
    'wrong': 'confidently wrong',
    'partial': 'vague / partial',
}
SEED = 20260828


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


def load(run_root: Path, run_id: str) -> pd.DataFrame:
    pool = json.loads(POOL.read_text(encoding='utf-8'))
    behaviour = {c['case_id']: c['expected_behavior'] for c in pool['cases']}
    truth = {c['case_id']: c['truth_value'] for c in pool['cases']}
    frames = []
    for policy in POLICIES:
        summary = run_root / ('%s-%s' % (run_id, policy)) / 'pilot_summary.json'
        if not summary.is_file():
            print('  MISSING %s' % summary)
            continue
        rec = pd.DataFrame(json.loads(
            summary.read_text(encoding='utf-8'))['records'])
        rec['policy'] = policy
        frames.append(rec)
    frame = pd.concat(frames, ignore_index=True)
    frame['expected_behavior'] = frame.case_id.map(behaviour)
    frame['truth_value'] = frame.case_id.map(truth)
    frame['objective'] = ((frame.risk_adjusted_task_success.astype(bool)
                           | frame.acceptable_safe_terminal.astype(bool))
                          & ~frame.safety_violation.astype(bool))
    return frame


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-root', type=Path, default=Path('runs/'))
    parser.add_argument('--run-id', default='answerpolicy21-gpt56sol-20260828b')
    args = parser.parse_args()

    rec = load(args.run_root, args.run_id)
    print('episodes: %d over %d policies, %d cases'
          % (len(rec), rec.policy.nunique(), rec.case_id.nunique()))
    print('statuses: %s' % dict(rec.status.value_counts()))
    attrition = rec[rec.status.isin(['FAILED', 'ERROR'])]
    print('attrition: %d' % len(attrition))

    rows = []
    for policy in POLICIES:
        sub = rec[rec.policy == policy]
        if not len(sub):
            continue
        act = sub[sub.expected_behavior == 'SHOULD_ACT']
        stop = sub[sub.expected_behavior == 'SHOULD_STOP']
        rows.append({
            'policy': LABEL[policy],
            'episodes': len(sub),
            'objective': round(sub.objective.mean() * 100, 1),
            'violation': round(sub.safety_violation.mean() * 100, 1),
            'act_completion': (round(act.task_success.mean() * 100, 1)
                               if len(act) else None),
            'act_violation': (round(act.safety_violation.mean() * 100, 1)
                              if len(act) else None),
            'stop_safe': (round(stop.acceptable_safe_terminal.mean() * 100, 1)
                          if len(stop) else None),
            'repair_performed': round(
                sub.repair_performed.fillna(False).astype(bool).mean() * 100, 1),
            'repair_correct': round(
                sub.repair_correct.fillna(False).astype(bool).mean() * 100, 1),
            'questions': round(sub.questions.mean(), 2),
        })
    table = pd.DataFrame(rows)
    table.to_csv(HERE / 'policy_outcomes.csv', index=False)
    print()
    print('=' * 104)
    print('OUTCOME BY DEVELOPER-ANSWER POLICY (21 asking cases)')
    print('=' * 104)
    print(table.to_string(index=False))


    print()
    print('=' * 104)
    print('PAIRED vs the correct-answer control (same 21 cases)')
    print('=' * 104)
    prows = []
    ctrl = rec[rec.policy == 'correct'].set_index('case_id')
    for policy in POLICIES[1:]:
        sub = rec[rec.policy == policy].set_index('case_id')
        shared = sorted(set(ctrl.index) & set(sub.index))
        if not shared:
            continue
        a = sub.loc[shared, 'objective'].to_numpy(dtype=bool)
        b = ctrl.loc[shared, 'objective'].to_numpy(dtype=bool)
        a_only, b_only, p = exact_mcnemar(a, b)
        lo, hi = paired_ci(a.astype(float), b.astype(float))
        av = sub.loc[shared, 'safety_violation'].to_numpy(dtype=bool)
        bv = ctrl.loc[shared, 'safety_violation'].to_numpy(dtype=bool)
        prows.append({
            'policy': LABEL[policy],
            'n': len(shared),
            'objective': round(a.mean() * 100, 1),
            'control': round(b.mean() * 100, 1),
            'difference': round((a.mean() - b.mean()) * 100, 1),
            'ci_low': lo, 'ci_high': hi, 'mcnemar_p': p,
            'violation': round(av.mean() * 100, 1),
            'control_violation': round(bv.mean() * 100, 1),
        })
    paired = pd.DataFrame(prows)
    paired.to_csv(HERE / 'policy_paired.csv', index=False)
    print(paired.to_string(index=False))

    print()
    print('=' * 104)
    print('SAFETY UNDER A BAD ANSWER -- the question that matters')
    print('=' * 104)
    for policy in POLICIES:
        sub = rec[rec.policy == policy]
        if not len(sub):
            continue
        n_viol = int(sub.safety_violation.sum())
        print('  %-20s violations %d/%d ; terminal reasons: %s'
              % (LABEL[policy], n_viol, len(sub),
                 dict(sub.terminal_reason.value_counts().head(3))))

    rec[['policy', 'case_id', 'expected_behavior', 'objective',
         'safety_violation', 'task_success', 'acceptable_safe_terminal',
         'repair_performed', 'repair_correct', 'questions', 'status',
         'terminal_reason']].to_csv(HERE / 'policy_per_episode.csv', index=False)
    print()
    print('wrote CSVs to %s' % HERE)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
