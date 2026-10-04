from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PRIMARY = REPO / 'paper_experiments/results/shared/permission_matched_v10_all_arms_20260819.xlsx'
RQ5 = REPO / 'paper_experiments/results/rq5/rq5_results.xlsx'
EPISODE_CSV = REPO / 'paper_experiments/analysis/interruption_20260828/interruptions_per_episode.csv'
FULL = 'statewise_v2_contract_corrected_typedfix'

NAMES = {
    'correct': 'Correct memory (oracle)', 'corrupted': 'Corrupted memory',
    'no_memory': 'No memory', 'bare_approval': 'Bare approval',
    'rationale_approval': 'Rationale approval',
    'generic_clarification': 'Clarification', 'memlineage_trust': 'MemLineage',
    'safety_sentry': 'Safety Sentry', 'ask_or_assume': 'Ask-or-Assume',
    'oracle_statewise': 'Oracle StateWise', FULL: 'StateWise',
}
ORDER = ['Correct memory (oracle)', 'Corrupted memory', 'No memory',
         'Bare approval', 'Rationale approval', 'Clarification',
         'MemLineage', 'Safety Sentry', 'Ask-or-Assume', 'Oracle StateWise',
         'StateWise']


def single_episode() -> pd.DataFrame:
    per = pd.read_csv(EPISODE_CSV)
    rows = []
    for arm, name in NAMES.items():
        sub = per[per.arm == arm]
        if not len(sub):
            continue
        safe = int(sub.safe_completion.sum())
        interruptions = float(sub.interruptions.sum())
        rows.append({
            'method': name,
            'episodes': len(sub),
            'questions': int(sub.questions.sum()),
            'permission_prompts': int(sub.permission_interactions.sum()),
            'interruptions': int(interruptions),
            'episodes_interrupted_pct': round(
                (sub.interruptions > 0).mean() * 100, 1),
            'safe_completions': safe,
            'safe_completion_pct': round(sub.safe_completion.mean() * 100, 1),
            'interruptions_per_safe': (round(interruptions / safe, 2)
                                       if safe else None),
            'safe_per_interruption': (round(safe / interruptions, 2)
                                      if interruptions else None),
        })
    return pd.DataFrame(rows).set_index('method').reindex(
        [n for n in ORDER if n in {r['method'] for r in rows}]).reset_index()


def longitudinal() -> pd.DataFrame:
    x = pd.ExcelFile(RQ5)
    seq = x.parse('Sequence_Data')
    seq = seq[seq.primary_in_scope == True]
    task = x.parse('Task_Data')
    rows = []
    for arm, name in NAMES.items():
        sub = seq[seq.arm == arm]
        if not len(sub):
            continue
        tsub = task[task.arm == arm]
        interruptions = (sub.cumulative_questions
                         + sub.cumulative_permission_interactions)
        strict = ((sub.future_task_success_rate >= 1.0)
                  & (sub.cumulative_safety_violations == 0))
        n_strict = int(strict.sum())
        total = float(interruptions.sum())


        later = tsub[tsub.task_index > 1]
        rows.append({
            'method': name,
            'sequences': len(sub),
            'questions_per_seq': round(sub.cumulative_questions.mean(), 2),
            'permission_prompts_per_seq': round(
                sub.cumulative_permission_interactions.mean(), 2),
            'interruptions_per_seq': round(interruptions.mean(), 2),
            'interruptions_max': int(interruptions.max()),
            'repeated_intervention_pct': round(
                sub.repeated_intervention_rate.mean() * 100, 1),
            'strict_sequences': n_strict,
            'strict_pct': round(strict.mean() * 100, 1),
            'later_task_success_pct': round(later.task_success.mean() * 100, 1),
            'interruptions_per_strict_seq': (round(total / n_strict, 2)
                                             if n_strict else None),
        })
    return pd.DataFrame(rows).set_index('method').reindex(
        [n for n in ORDER if n in {r['method'] for r in rows}]).reset_index()


def main() -> None:
    single = single_episode()
    single.to_csv(HERE / 'humancost_single_episode.csv', index=False)
    print('=' * 118)
    print('HUMAN COST -- single-episode pool (frozen 150 cases, all arms)')
    print('=' * 118)
    print(single.to_string(index=False))

    long = longitudinal()
    long.to_csv(HERE / 'humancost_longitudinal.csv', index=False)
    print()
    print('=' * 118)
    print('HUMAN COST -- longitudinal pool (32 four-task sequences, all arms)')
    print('=' * 118)
    print(long.to_string(index=False))

    print()
    print('=' * 118)
    print('READING')
    print('=' * 118)
    print('Arms that never interrupt (MemLineage) have a 0.00 ratio and near-zero')
    print('outcome: the ratio is only meaningful read against the outcome column.')
    print()
    for name in ('Ask-or-Assume', 'Safety Sentry', 'Clarification', 'StateWise'):
        r = single[single.method == name]
        if not len(r):
            continue
        r = r.iloc[0]
        print('  %-24s %3d interruptions -> %3d safe (%s per safe)'
              % (name, r.interruptions, r.safe_completions,
                 r.interruptions_per_safe))
    print()
    print('wrote CSVs to %s' % HERE)


if __name__ == '__main__':
    main()
