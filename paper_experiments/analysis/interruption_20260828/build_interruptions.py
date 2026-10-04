from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PRIMARY = REPO / 'paper_experiments/results/shared/permission_matched_v10_all_arms_20260819.xlsx'
SW_RUNS = Path('runs/')
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
ORDER = [NAMES[a] for a in (
    'correct', 'corrupted', 'no_memory', 'bare_approval', 'rationale_approval',
    'generic_clarification', 'memlineage_trust', 'safety_sentry',
    'ask_or_assume', FULL)]


def load_raw() -> pd.DataFrame:

    frames = []
    for run_dir in sorted(SW_RUNS.iterdir()):
        summary = run_dir / 'pilot_summary.json'
        if not summary.is_file():
            continue
        try:
            payload = json.loads(summary.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        records = payload.get('records')
        if not records:
            continue
        frame = pd.DataFrame(records)
        if 'questions' not in frame.columns:
            continue
        frame['run_id'] = run_dir.name
        frames.append(frame[[
            c for c in ('run_id', 'case_id', 'arm', 'trial', 'questions',
                        'permission_interactions', 'human_interactions',
                        'status')
            if c in frame.columns]])
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    head = pd.ExcelFile(PRIMARY).parse('Combined_Episodes')
    head['safe_completion'] = (
        (head.risk_adjusted_task_success.astype(bool)
         | head.acceptable_safe_terminal.astype(bool))
        & ~head.safety_violation.astype(bool))
    print('headline episodes: %d (%d arms x %d cases)'
          % (len(head), head.arm.nunique(), head.case_id.nunique()))

    raw = load_raw()


    exact = raw.drop_duplicates(['run_id', 'arm', 'case_id'])
    fallback = (raw.sort_values('run_id')
                .drop_duplicates(['arm', 'case_id'], keep='last'))

    merged = head.merge(
        exact[['run_id', 'arm', 'case_id', 'questions',
               'permission_interactions']],
        on=['run_id', 'arm', 'case_id'], how='left')
    missing = merged.questions.isna()
    if missing.any():
        patch = merged[missing].drop(
            columns=['questions', 'permission_interactions']).merge(
            fallback[['arm', 'case_id', 'questions',
                      'permission_interactions']],
            on=['arm', 'case_id'], how='left')
        merged = pd.concat([merged[~missing], patch], ignore_index=True)
    still = int(merged.questions.isna().sum())
    print('episodes matched to a raw record: %d / %d (unmatched %d)'
          % (len(merged) - still, len(merged), still))
    if still:
        print('  unmatched by arm: %s'
              % merged[merged.questions.isna()].arm.value_counts().to_dict())

    merged['questions'] = merged.questions.fillna(0)
    merged['permission_interactions'] = (
        merged.permission_interactions.fillna(0))
    merged['interruptions'] = (merged.questions
                               + merged.permission_interactions)
    merged['method'] = merged.arm.map(NAMES)

    rows = []
    for arm, name in NAMES.items():
        sub = merged[merged.arm == arm]
        safe = int(sub.safe_completion.sum())
        total_int = float(sub.interruptions.sum())
        rows.append({
            'method': name,
            'episodes': len(sub),
            'questions_total': int(sub.questions.sum()),
            'perms_total': int(sub.permission_interactions.sum()),
            'interruptions_total': int(total_int),
            'interrupted_episodes_pct': round(
                (sub.interruptions > 0).mean() * 100, 1),
            'interruptions_per_episode': round(sub.interruptions.mean(), 2),
            'safe_completions': safe,
            'interruptions_per_safe_completion': (
                round(total_int / safe, 2) if safe else None),
            'safe_completions_per_interruption': (
                round(safe / total_int, 2) if total_int else None),
        })
    table = pd.DataFrame(rows).set_index('method').reindex(ORDER).reset_index()
    table.to_csv(HERE / 'interruptions.csv', index=False)
    print()
    print('=' * 100)
    print('DEVELOPER INTERRUPTIONS on the frozen 150-case set')
    print('=' * 100)
    print(table.to_string(index=False))

    print()
    print('=' * 100)
    print('THE ASK-OR-ASSUME COMPARISON')
    print('=' * 100)
    for name in ('Ask-or-Assume', 'Clarification', 'StateWise'):
        row = table[table.method == name].iloc[0]
        per_safe = row.interruptions_per_safe_completion
        print('  %-16s %3d interruptions over %d episodes -> %3d safe '
              'completions  (%s interruptions per safe completion)'
              % (name, row.interruptions_total, row.episodes,
                 row.safe_completions,
                 'n/a' if per_safe is None else '%.2f' % per_safe))


    print()
    print('interruption-count distribution per arm (episodes):')
    dist = pd.crosstab(merged.method, merged.interruptions.astype(int))
    print(dist.reindex(ORDER).to_string())
    dist.reindex(ORDER).to_csv(HERE / 'interruption_distribution.csv')

    merged[['arm', 'method', 'case_id', 'questions',
            'permission_interactions', 'interruptions', 'safe_completion',
            'expected_behavior', 'domain']].to_csv(
        HERE / 'interruptions_per_episode.csv', index=False)
    print()
    print('wrote CSVs to %s' % HERE)


if __name__ == '__main__':
    main()
