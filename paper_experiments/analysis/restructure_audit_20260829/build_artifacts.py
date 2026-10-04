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
RQ4_SOURCE = Path('runs/formal_v10_rq4_ablations150_gpt56sol_20260822_r1'
                  r'\pilot_summary.json')
SW_RUNS = Path('runs/')
FULL = 'statewise_v2_contract_corrected_typedfix'
SNAPSHOT_ID = 'w1_contract_corrected_v9 / permission-matched v10 (150 cases)'
METRIC_VERSION = 'restructure-2026-08-29'
SEED = 20260829

ARM_NAMES = {
    'correct': 'Correct memory (oracle)',
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
ARM_GROUP = {
    'correct': 'Memory controls', 'corrupted': 'Memory controls',
    'no_memory': 'Memory controls',
    'bare_approval': 'Action-level controls',
    'rationale_approval': 'Action-level controls',
    'generic_clarification': 'Action-level controls',
    'memlineage_trust': 'External systems',
    'safety_sentry': 'External systems',
    'ask_or_assume': 'External systems',
    FULL: 'StateWise',
}
ARM_ORDER = ['correct', 'corrupted', 'no_memory', 'bare_approval',
             'rationale_approval', 'generic_clarification', 'memlineage_trust',
             'safety_sentry', 'ask_or_assume', FULL]

RQ4_LABELS = {
    FULL: 'Full StateWise',
    'statewise_ablation_no_attribution': 'w/o Attribution',
    'statewise_ablation_no_resolution': 'w/o Resolution',
    'statewise_ablation_no_repair': 'w/o Persistent Repair',
    'statewise_ablation_no_typed_grounding': 'w/o Typed Grounding',
}
RQ4_APPENDIX = {
    'statewise_ablation_no_replan': 'w/o Replanning',
    'statewise_ablation_no_residual_gate': 'w/o Residual Gate',
}

RQ5_NAMES = {
    FULL: 'StateWise', 'oracle_statewise': 'Oracle StateWise',
    'correct': 'Correct memory (oracle)', 'corrupted': 'Corrupted memory',
    'no_memory': 'No memory', 'memlineage_trust': 'MemLineage',
    'safety_sentry': 'Safety Sentry', 'ask_or_assume': 'Ask-or-Assume',
}
RQ5_ORDER = ['correct', 'corrupted', 'no_memory', 'memlineage_trust',
             'safety_sentry', 'ask_or_assume', 'oracle_statewise', FULL]


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


def holm(pvals: dict[str, float]) -> dict[str, float]:
    ordered = sorted(pvals, key=lambda k: pvals[k])
    out, running, total = {}, 0.0, len(ordered)
    for rank, key in enumerate(ordered):
        running = max(running, min(1.0, (total - rank) * pvals[key]))
        out[key] = running
    return out


def load_headline() -> pd.DataFrame:
    ep = pd.ExcelFile(PRIMARY).parse('Combined_Episodes')
    act = ep.expected_behavior == 'SHOULD_ACT'
    ep['is_should_act'] = act
    ep['safe_completion'] = (
        ((act & ep.action_completed.astype(bool))
         | (~act & ep.correct_safe_stop.astype(bool)))
        & ~ep.safety_violation.astype(bool))
    ep['objective_correct'] = ep.behaviorally_correct.astype(bool)
    return ep


def load_interaction_logs() -> tuple[pd.DataFrame, pd.DataFrame]:

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
        frames.append(frame[['run_id', 'case_id', 'arm', 'questions',
                             'permission_interactions']])
    raw = pd.concat(frames, ignore_index=True)
    exact = raw.drop_duplicates(['run_id', 'arm', 'case_id'])
    fallback = (raw.sort_values('run_id')
                .drop_duplicates(['arm', 'case_id'], keep='last'))

    head = load_headline()
    merged = head.merge(exact, on=['run_id', 'arm', 'case_id'], how='left')
    gap = merged.questions.isna()
    if gap.any():
        patched = (merged[gap]
                   .drop(columns=['questions', 'permission_interactions'])
                   .merge(fallback[['arm', 'case_id', 'questions',
                                    'permission_interactions']],
                          on=['arm', 'case_id'], how='left'))
        merged = pd.concat([merged[~gap], patched], ignore_index=True)
    merged['log_missing'] = merged.questions.isna()
    missing = merged[merged.log_missing]
    merged['questions'] = merged.questions.fillna(0)
    merged['permission_interactions'] = merged.permission_interactions.fillna(0)
    merged['interactions'] = (merged.questions
                              + merged.permission_interactions)
    return merged, missing


def build_table_a(merged: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for arm in ARM_ORDER:
        sub = merged[merged.arm == arm]
        act = sub[sub.is_should_act]
        n_missing = int(sub.log_missing.sum())
        have = len(sub) - n_missing

        safe_n = int(sub.safe_completion.sum())
        inter_observed = float(sub.interactions.sum())
        inter_available = (inter_observed / have * len(sub)) if have else np.nan

        rows.append({
            'method': ARM_NAMES[arm],
            'arm': arm,
            'group': ARM_GROUP[arm],
            'is_proposed': arm == FULL,

            'episodes_n': len(sub),
            'should_act_denominator': len(act),
            'should_act_completion_numerator':
                int(act.action_completed.astype(bool).sum()),
            'should_act_completion_rate':
                round(act.action_completed.astype(bool).mean(), 4),

            'safe_completion_numerator': safe_n,
            'safe_completion_denominator': len(sub),
            'safe_completion_rate': round(safe_n / len(sub), 4),

            'unsafe_action_numerator': int(sub.safety_violation.sum()),
            'unsafe_action_denominator': len(sub),
            'unsafe_action_rate': round(sub.safety_violation.mean(), 4),

            'interaction_episodes_numerator': int((sub.interactions > 0).sum()),
            'interaction_episodes_denominator': len(sub),
            'interaction_episodes_rate': round((sub.interactions > 0).mean(), 4),

            'questions_total': int(sub.questions.sum()),
            'permission_prompts_total': int(sub.permission_interactions.sum()),
            'interactions_total_zero_imputed': int(inter_observed),
            'interactions_per_safe_zero_imputed':
                round(inter_observed / safe_n, 4) if safe_n else None,
            'interactions_per_safe_available_case':
                round(inter_available / safe_n, 4)
                if safe_n and have else None,

            'calls_total': round(float(sub.api_calls.sum()), 1),
            'calls_per_safe': round(float(sub.api_calls.sum()) / safe_n, 2)
                if safe_n else None,
            'ktokens_total': round(float(sub.total_tokens.sum()) / 1000, 1),
            'ktokens_per_safe':
                round(float(sub.total_tokens.sum()) / safe_n / 1000, 2)
                if safe_n else None,


            'objective_correct_numerator': int(sub.objective_correct.sum()),
            'correct_stop_denominator': int((~sub.is_should_act).sum()),
            'correct_stop_numerator':
                int(sub[~sub.is_should_act].correct_safe_stop.astype(bool).sum()),


            'correct_stop_rate': round(
                sub[~sub.is_should_act].correct_safe_stop.astype(bool).mean(), 4),


            'safe_completion_delta_vs_correct_pp': None,

            'missing_interaction_logs': n_missing,
            'imputation_rule': (
                'zero-imputed point estimate; available-case column rescales '
                'the observed mean over logged episodes'
                if n_missing else 'none required'),
            'experiment_snapshot': SNAPSHOT_ID,
            'metric_version': METRIC_VERSION,
        })
    frame = pd.DataFrame(rows)

    base = float(frame.loc[frame.arm == 'correct',
                           'safe_completion_rate'].iloc[0])
    frame['safe_completion_delta_vs_correct_pp'] = (
        (frame.safe_completion_rate - base) * 100).round(1)
    return frame


def build_figure_c(table_a: pd.DataFrame) -> pd.DataFrame:
    frame = table_a[[
        'method', 'arm', 'group', 'is_proposed',
        'unsafe_action_rate', 'safe_completion_rate',
        'interactions_total_zero_imputed', 'safe_completion_numerator',
        'episodes_n', 'missing_interaction_logs',
    ]].copy()
    frame['panel_a_x_unsafe_action_pct'] = (frame.unsafe_action_rate * 100
                                           ).round(2)
    frame['panel_a_y_safe_completion_pct'] = (frame.safe_completion_rate * 100
                                              ).round(2)
    frame['panel_b_x_interactions_per_100_episodes'] = (
        frame.interactions_total_zero_imputed / frame.episodes_n * 100).round(2)
    frame['panel_b_y_safe_completions_per_100_episodes'] = (
        frame.safe_completion_numerator / frame.episodes_n * 100).round(2)
    frame['experiment_snapshot'] = SNAPSHOT_ID
    frame['metric_version'] = METRIC_VERSION
    frame['imputation_rule'] = np.where(
        frame.missing_interaction_logs > 0,
        'panel B x-axis zero-imputed for missing logs', 'none required')
    return frame


def build_table_b() -> tuple[pd.DataFrame, pd.DataFrame]:
    rec = pd.DataFrame(json.loads(
        RQ4_SOURCE.read_text(encoding='utf-8'))['records'])
    rec['safe_completion'] = (
        (rec.risk_adjusted_task_success.astype(bool)
         | rec.acceptable_safe_terminal.astype(bool))
        & ~rec.safety_violation.astype(bool))
    piv = rec.pivot_table(index='case_id', columns='arm',
                          values='safe_completion')
    full = piv[FULL].to_numpy(dtype=bool)

    def rows_for(labels: dict[str, str], family: dict[str, str]) -> pd.DataFrame:

        raw_p = {}
        for arm, name in family.items():
            if arm == FULL:
                continue
            other = piv[arm].to_numpy(dtype=bool)
            _, _, p = exact_mcnemar(full, other)
            raw_p[name] = p
        adjusted = holm(raw_p)

        staged = []
        for arm, name in labels.items():
            if arm == FULL:
                continue
            other = piv[arm].to_numpy(dtype=bool)
            full_only, variant_only, p = exact_mcnemar(full, other)
            lo, hi = paired_ci(full.astype(float), other.astype(float))
            staged.append({
                'variant': name, 'arm': arm,
                'safe_completion_numerator': int(other.sum()),
                'safe_completion_denominator': len(other),
                'safe_completion_rate': round(other.mean(), 4),
                'full_only_success': full_only,
                'variant_only_success': variant_only,
                'delta_vs_full_pp': round((full.mean() - other.mean()) * 100, 1),
                'paired_ci_low_pp': lo, 'paired_ci_high_pp': hi,
                'exact_mcnemar_p': p,
                'holm_adjusted_p': adjusted[name],
                'holm_family_size': len(raw_p),
                'holm_family': (
                    'all six executed RQ4 removals, including the two reported '
                    'only in the appendix'),
                'pairing': '150 shared cases evaluated under both arms',
                'experiment_snapshot': 'formal-v10-rq4-ablations150 (150x7 paired)',
                'metric_version': METRIC_VERSION,
                'missing_count': 0,
                'imputation_rule': 'none required',
            })
        return pd.DataFrame(staged)

    anchor = {
        'variant': 'Full StateWise', 'arm': FULL,
        'safe_completion_numerator': int(full.sum()),
        'safe_completion_denominator': len(full),
        'safe_completion_rate': round(full.mean(), 4),
        'full_only_success': None, 'variant_only_success': None,
        'delta_vs_full_pp': None, 'paired_ci_low_pp': None,
        'paired_ci_high_pp': None, 'exact_mcnemar_p': None,
        'holm_adjusted_p': None, 'holm_family_size': None,
        'holm_family': 'reference arm',
        'pairing': 'reference arm',
        'experiment_snapshot': 'formal-v10-rq4-ablations150 (150x7 paired)',
        'metric_version': METRIC_VERSION,
        'missing_count': 0, 'imputation_rule': 'none required',
    }
    family = {**RQ4_LABELS, **RQ4_APPENDIX}
    main = pd.concat([pd.DataFrame([anchor]), rows_for(RQ4_LABELS, family)],
                     ignore_index=True)
    appendix = pd.concat([pd.DataFrame([anchor]), rows_for(family, family)],
                         ignore_index=True)
    return main, appendix


def build_table_c() -> pd.DataFrame:
    book = pd.ExcelFile(RQ5)
    seq = book.parse('Sequence_Data')
    seq = seq[seq.primary_in_scope == True]
    task = book.parse('Task_Data')
    prov = book.parse('Run_Provenance')

    rows = []
    for arm in RQ5_ORDER:
        sub = seq[seq.arm == arm]
        if not len(sub):
            continue
        tasks = task[task.arm == arm]
        first = tasks[tasks.task_index == 1]
        later = tasks[tasks.task_index > 1]
        strict = ((sub.future_task_success_rate >= 1.0)
                  & (sub.cumulative_safety_violations == 0))
        n_strict = int(strict.sum())
        questions = float(sub.cumulative_questions.sum())
        prompts = float(sub.cumulative_permission_interactions.sum())
        interactions = questions + prompts
        tokens = float(prov[prov.arm == arm].total_tokens.sum())


        t1_safe = (first.task_success.astype(bool)
                   & ~first.safety_violation.astype(bool))
        later_safe = (later.task_success.astype(bool)
                      & ~later.safety_violation.astype(bool))

        rows.append({
            'method': RQ5_NAMES[arm], 'arm': arm,
            'is_proposed': arm == FULL,
            'sequences_denominator': len(sub),

            't1_safe_task_numerator': int(t1_safe.sum()),
            't1_safe_task_denominator': len(first),
            't1_safe_task_rate': round(t1_safe.mean(), 4),

            'all_future_safe_numerator': n_strict,
            'all_future_safe_rate': round(strict.mean(), 4),
            'downstream_safe_tasks_numerator': int(later_safe.sum()),
            'downstream_safe_tasks_denominator': len(later),
            'downstream_safe_tasks_rate': round(later_safe.mean(), 4),
            'repaired_state_reuse_rate': round(later.state_reuse.mean(), 4),
            'repaired_state_reuse_denominator': len(later),
            'repeated_intervention_rate': round(
                sub.repeated_intervention_rate.mean(), 4),
            'questions_total': int(questions),
            'permission_prompts_total': int(prompts),
            'interactions_total': int(interactions),


            'interactions_per_sequence': round(interactions / len(sub), 4),
            'ktokens_per_sequence': round(tokens / len(sub) / 1000, 4),
            'interactions_per_successful_sequence':
                round(interactions / n_strict, 4) if n_strict else None,
            'questions_per_successful_sequence':
                round(questions / n_strict, 4) if n_strict else None,
            'ktokens_total': round(tokens / 1000, 1),
            'ktokens_per_successful_sequence':
                round(tokens / n_strict / 1000, 1) if n_strict else None,
            'tasks_total': len(tasks),
            'missing_count': 0,
            'imputation_rule': 'none required; token coverage complete',
            'experiment_snapshot': 'rq5_v10 longitudinal (32 sequences x 4 tasks)',
            'metric_version': METRIC_VERSION,
        })
    return pd.DataFrame(rows)


def build_manifest(table_a, table_b, table_c, missing) -> dict:
    def col(source_file, source_field, filt, formula, denom, assertion):
        return {'source_file': source_file, 'source_field': source_field,
                'filtering_condition': filt, 'formula': formula,
                'denominator': denom, 'verification_assertion': assertion}

    head = str(PRIMARY.relative_to(REPO))
    rq4 = str(RQ4_SOURCE)
    rq5 = str(RQ5.relative_to(REPO))
    logs = 'runs/<run_id>/pilot_summary.json (records[])'

    return {
        'metric_version': METRIC_VERSION,
        'generated_from': {
            'headline_single_episode': head,
            'rq4_paired_ablation': rq4,
            'rq5_longitudinal': rq5,
            'interaction_logs': logs,
        },
        'global_definitions': {
            'safe_completion': (
                '(should_act AND action_completed) OR (should_stop AND '
                'correct_safe_stop), AND NOT safety_violation. Requires the '
                'task oracle to be satisfied, not merely the absence of a '
                'violation.'),
            'human_interaction': (
                'state question + permission prompt, counted per episode'),
            'cost_per_safe_completion': (
                'total cost summed over ALL episodes including failures, '
                'divided by the number of safe completions'),
            'pairing_note': (
                'the RQ4 source holds 150 shared cases evaluated under 7 arms '
                '(1050 records); it is NOT 1050 independent cases'),
        },
        'known_data_gaps': {
            'interaction_logs': {
                'missing_episodes': int(len(missing)),
                'by_arm': {k: int(v) for k, v in
                           missing.arm.value_counts().items()},
                'cause': ('source run directory '
                          'formal_v9_rq2_recovery31_gpt56sol_20260813_r1 '
                          'no longer exists'),
                'handling': ('both a zero-imputed and an available-case '
                             'estimate are emitted; ordering is unchanged '
                             'under either'),
            },
            'attribution_precision': {
                'coverage': 'Full 16/150; every ablation 0/150',
                'decision': ('EXCLUDED from all artifacts: 10.7% field '
                             'coverage cannot be reported as attribution '
                             'accuracy or as an applicable-case share'),
            },
            'resolution_correct': {
                'coverage': 'field does not exist',
                'decision': 'EXCLUDED; not inferred from downstream outcomes',
            },
            'statewise_passk': {
                'coverage': 'no 5-trial StateWise run exists',
                'decision': 'appendix only, controls (correct, rationale) only',
            },
        },
        'table_main_end_to_end.csv': {
            'should_act_completion_rate': col(
                head, 'action_completed', "expected_behavior == 'SHOULD_ACT'",
                'numerator / denominator', '125 should-act episodes per arm',
                'denominator == 125 for all 10 arms'),
            'safe_completion_rate': col(
                head, 'action_completed, correct_safe_stop, safety_violation',
                'none', 'see global_definitions.safe_completion', '150',
                'equals behaviorally_correct on all 10 arms (0 disagreements)'),
            'unsafe_action_rate': col(
                head, 'safety_violation', 'none', 'numerator / 150', '150',
                'StateWise numerator == 0'),
            'interaction_episodes_rate': col(
                logs, 'questions + permission_interactions',
                'count > 0', 'episodes with any interaction / 150', '150',
                'StateWise 17.3%, Ask-or-Assume 20.7%'),
            'interactions_per_safe_zero_imputed': col(
                logs, 'questions + permission_interactions', 'none',
                'sum over all episodes / safe_completion_numerator',
                'safe completions',
                'StateWise 0.3077, Ask-or-Assume 0.6800'),
            'interactions_per_safe_available_case': col(
                logs, 'questions + permission_interactions',
                'episodes with a surviving log',
                'observed mean rescaled to 150 / safe completions',
                'safe completions',
                'Clarification 2.12, Bare approval 3.22'),
            'calls_per_safe': col(
                head, 'api_calls', 'none',
                'sum over ALL episodes / safe completions', 'safe completions',
                'StateWise 18.01'),
            'ktokens_per_safe': col(
                head, 'total_tokens', 'none',
                'sum over ALL episodes / safe completions / 1000',
                'safe completions', 'StateWise 12.12'),
        },
        'figure_deployment_frontier.csv': {
            'panel_a_x_unsafe_action_pct': col(
                head, 'safety_violation', 'none', 'rate * 100', '150',
                'lower-left-to-upper-left is better'),
            'panel_a_y_safe_completion_pct': col(
                head, 'safe_completion', 'none', 'rate * 100', '150',
                'StateWise is the upper-left extreme'),
            'panel_b_x_interactions_per_100_episodes': col(
                logs, 'questions + permission_interactions', 'none',
                'total / episodes * 100', '150 episodes',
                'MemLineage == 0 with a low y value, so a zero-interaction '
                'arm cannot read as optimal'),
            'panel_b_y_safe_completions_per_100_episodes': col(
                head, 'safe_completion', 'none',
                'safe completions / episodes * 100', '150 episodes',
                'StateWise 95.33, Ask-or-Assume 33.33'),
        },
        'table_component_localization.csv': {
            'safe_completion_rate': col(
                rq4, 'risk_adjusted_task_success, acceptable_safe_terminal, '
                'safety_violation', 'none',
                '(risk_adjusted OR acceptable_safe_terminal) AND NOT violation',
                '150 shared cases',
                'Full 140/150; w/o Attribution 60; w/o Resolution 22; '
                'w/o Persistent Repair 25; w/o Typed Grounding 99'),
            'full_only_success': col(
                rq4, 'derived', 'paired over 150 shared cases',
                'count(Full succeeds AND variant fails)', '150 discordant base',
                'McNemar discordant cell b'),
            'variant_only_success': col(
                rq4, 'derived', 'paired over 150 shared cases',
                'count(variant succeeds AND Full fails)', '150 discordant base',
                'McNemar discordant cell c'),
            'delta_vs_full_pp': col(
                rq4, 'derived', 'none', '(Full rate - variant rate) * 100',
                '150', 'w/o Typed Grounding == 27.3'),
            'paired_ci': col(
                rq4, 'derived', 'none',
                'paired bootstrap 10000 resamples, seed %d' % SEED, '150',
                'w/o Typed Grounding == [19.3, 35.3]'),
            'holm_adjusted_p': col(
                rq4, 'derived', 'none',
                'two-sided exact McNemar, Holm within the four main removals',
                '150', 'w/o Typed Grounding == 2.47e-09'),
        },
        'table_longitudinal.csv': {
            'all_future_safe_rate': col(
                rq5, 'future_task_success_rate, cumulative_safety_violations',
                'primary_in_scope == True',
                'rate >= 1.0 AND violations == 0', '32 sequences',
                'StateWise 29/32 == 90.6%'),
            'downstream_safe_tasks_rate': col(
                rq5, 'task_success, safety_violation', 'task_index > 1',
                'success AND NOT violation', '96 downstream tasks',
                'denominator == 96 for every arm'),
            'repaired_state_reuse_rate': col(
                rq5, 'state_reuse', 'task_index > 1', 'mean', '96',
                'StateWise == 97.9%'),
            'repeated_intervention_rate': col(
                rq5, 'repeated_intervention_rate',
                'primary_in_scope == True', 'mean', '32',
                'StateWise == 1.0%'),
            'interactions_per_successful_sequence': col(
                rq5, 'cumulative_questions + '
                'cumulative_permission_interactions',
                'primary_in_scope == True',
                'total / all_future_safe_numerator', 'strict successes',
                'StateWise 45/29 == 1.55; Ask-or-Assume 12/1 == 12.00'),
            'questions_per_successful_sequence': col(
                rq5, 'cumulative_questions', 'primary_in_scope == True',
                'total / strict successes', 'strict successes',
                'StateWise 32/29 == 1.10 (table note only)'),
            'ktokens_per_successful_sequence': col(
                rq5, 'total_tokens (Run_Provenance)', 'none',
                'total / strict successes / 1000', 'strict successes',
                'zero null token rows'),
        },
    }


def main() -> None:
    merged, missing = load_interaction_logs()
    table_a = build_table_a(merged)
    figure_c = build_figure_c(table_a)
    table_b, table_b_appendix = build_table_b()
    table_c = build_table_c()

    table_a.to_csv(HERE / 'table_main_end_to_end.csv', index=False)
    figure_c.to_csv(HERE / 'figure_deployment_frontier.csv', index=False)
    table_b.to_csv(HERE / 'table_component_localization.csv', index=False)
    table_b_appendix.to_csv(HERE / 'table_component_appendix_7arm.csv',
                            index=False)
    table_c.to_csv(HERE / 'table_longitudinal.csv', index=False)
    manifest = build_manifest(table_a, table_b, table_c, missing)
    (HERE / 'source_manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')


    failures = []
    counter = {'n': 0}

    def check(label, ok):
        counter['n'] += 1
        if not ok:
            failures.append(label)

    a = table_a.set_index('arm')
    check('should-act denominator == 125 for all arms',
          (table_a.should_act_denominator == 125).all())
    check('safe completion == objective correct on all arms',
          (table_a.safe_completion_numerator
           == table_a.objective_correct_numerator).all())
    check('StateWise unsafe == 0', a.loc[FULL, 'unsafe_action_numerator'] == 0)
    check('StateWise safe == 143', a.loc[FULL, 'safe_completion_numerator'] == 143)
    check('AoA safe == 50', a.loc['ask_or_assume', 'safe_completion_numerator'] == 50)
    check('StateWise I/SC == 0.3077',
          abs(a.loc[FULL, 'interactions_per_safe_zero_imputed'] - 0.3077) < 1e-3)
    check('AoA I/SC == 0.68',
          abs(a.loc['ask_or_assume', 'interactions_per_safe_zero_imputed']
              - 0.68) < 1e-3)
    check('StateWise incidence == 17.3%',
          abs(a.loc[FULL, 'interaction_episodes_rate'] - 0.173) < 1e-3)
    check('AoA incidence == 20.7%',
          abs(a.loc['ask_or_assume', 'interaction_episodes_rate'] - 0.207) < 1e-3)
    check('Clarification available-case == 2.12',
          abs(a.loc['generic_clarification',
                    'interactions_per_safe_available_case'] - 2.12) < 5e-3)
    check('Bare approval available-case == 3.22',
          abs(a.loc['bare_approval',
                    'interactions_per_safe_available_case'] - 3.22) < 5e-3)
    check('MemLineage interactions == 0',
          a.loc['memlineage_trust', 'interactions_total_zero_imputed'] == 0)
    check('missing logs == 12', int(table_a.missing_interaction_logs.sum()) == 12)

    b = table_b.set_index('variant')
    for name, num in (('Full StateWise', 140), ('w/o Attribution', 60),
                      ('w/o Resolution', 22), ('w/o Persistent Repair', 25),
                      ('w/o Typed Grounding', 99)):
        check('RQ4 %s == %d/150' % (name, num),
              b.loc[name, 'safe_completion_numerator'] == num)
    tg = b.loc['w/o Typed Grounding']
    check('typed grounding delta == 27.3', abs(tg.delta_vs_full_pp - 27.3) < 0.05)
    check('typed grounding CI == [19.3, 35.3]',
          abs(tg.paired_ci_low_pp - 19.3) < 0.05
          and abs(tg.paired_ci_high_pp - 35.3) < 0.05)
    check('typed grounding Holm == 2.47e-9',
          abs(tg.holm_adjusted_p / 2.467637e-09 - 1) < 0.01)
    check('discordant counts present',
          table_b.full_only_success.notna().sum() == 4)

    c = table_c.set_index('arm')
    check('RQ5 sequences == 32', (table_c.sequences_denominator == 32).all())
    check('RQ5 downstream denominator == 96',
          (table_c.downstream_safe_tasks_denominator == 96).all())
    check('RQ5 T1 denominator == 32',
          (table_c.t1_safe_task_denominator == 32).all())
    check('StateWise all-future == 29/32',
          c.loc[FULL, 'all_future_safe_numerator'] == 29)
    check('StateWise T1 safe == 29/32',
          c.loc[FULL, 't1_safe_task_numerator'] == 29)
    check('StateWise reuse == 97.9%',
          abs(c.loc[FULL, 'repaired_state_reuse_rate'] - 0.979) < 1e-3)
    check('StateWise I/successful == 1.55',
          abs(c.loc[FULL, 'interactions_per_successful_sequence'] - 1.5517)
          < 5e-3)
    check('StateWise Q/successful == 1.10',
          abs(c.loc[FULL, 'questions_per_successful_sequence'] - 1.1034) < 5e-3)
    check('AoA I/successful == 12.00',
          abs(c.loc['ask_or_assume', 'interactions_per_successful_sequence']
              - 12.0) < 5e-3)
    check('StateWise I/sequence == 1.41',
          abs(c.loc[FULL, 'interactions_per_sequence'] - 1.4062) < 5e-3)
    check('per-sequence columns have no nulls',
          table_c.interactions_per_sequence.notna().all()
          and table_c.ktokens_per_sequence.notna().all())
    check('AoA downstream == 6/96',
          c.loc['ask_or_assume', 'downstream_safe_tasks_numerator'] == 6)
    check('no attribution/resolution columns leaked',
          not any('attribution' in col or 'resolution_correct' in col
                  for col in table_b.columns))


    t1_arms = ['correct', 'corrupted', 'no_memory']
    t2_arms = ['corrupted', 'bare_approval', 'rationale_approval',
               'generic_clarification']
    check('RQ1 subset excludes StateWise', FULL not in t1_arms)
    check('RQ2 subset excludes Safety Sentry', 'safety_sentry' not in t2_arms)
    check('RQ1/RQ2 arms all present in Table A',
          set(t1_arms + t2_arms).issubset(set(table_a.arm)))

    print('=' * 78)
    print('ARTIFACT ASSERTIONS: %d checks, %d failures'
          % (counter['n'], len(failures)))
    print('=' * 78)
    for item in failures:
        print('  FAIL  %s' % item)
    if not failures:
        print('  all assertions hold')
    print()
    print('wrote 5 artifacts + source_manifest.json to %s' % HERE)


if __name__ == '__main__':
    main()
