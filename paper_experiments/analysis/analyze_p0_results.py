import json
import glob
from pathlib import Path
from scipy import stats
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
EXPERIMENTS_DIR = PROJECT_ROOT / "runs" / "managed_pilot"

print("="*120)
print("P0 EXPERIMENTS ANALYSIS - CLAIM-EVIDENCE MAPPING")
print("="*120)
print()


print("EXPERIMENT 1: State Corruption Impact (RQ1)")
print("-"*120)
print("Claim: Persistent state errors independently cause wrong decisions & violations")
print()


exp1_results = {}
for arm in ['correct', 'corrupted', 'nomemory']:
    run_dir = EXPERIMENTS_DIR / f"exp1-{arm}-gpt56sol"
    summary_path = run_dir / "pilot_summary.json"

    if summary_path.exists():
        with open(summary_path) as f:
            data = json.load(f)
            exp1_results[arm] = data['table'][0]
            print(f"✓ Loaded {arm}: {exp1_results[arm]['episodes']} episodes")
    else:
        print(f"✗ Missing {arm}: {summary_path}")

print()

if len(exp1_results) == 3:

    metrics = {
        arm: {
            'accepted_terminal_rate': data['eligible_accepted_terminal'] / data['eligible_episodes'],
            'task_success_rate': data['eligible_task_success'] / data['eligible_episodes'],
            'safety_violation_rate': data['eligible_safety_violation'] / data['eligible_episodes'],
            'unnecessary_mutation_rate': data.get('unnecessary_mutation_rate', 0)
        }
        for arm, data in exp1_results.items()
    }

    print("Performance Comparison:")
    print(f"{'Arm':<15} {'Accepted Terminal':<20} {'Task Success':<20} {'Violations':<20}")
    print("-"*120)
    for arm in ['correct', 'corrupted', 'nomemory']:
        m = metrics[arm]
        print(f"{arm:<15} {m['accepted_terminal_rate']:<20.1%} {m['task_success_rate']:<20.1%} {m['safety_violation_rate']:<20.1%}")

    print()


    correct_success = [1] * exp1_results['correct']['eligible_accepted_terminal'] + \
                      [0] * (exp1_results['correct']['eligible_episodes'] - exp1_results['correct']['eligible_accepted_terminal'])
    corrupted_success = [1] * exp1_results['corrupted']['eligible_accepted_terminal'] + \
                        [0] * (exp1_results['corrupted']['eligible_episodes'] - exp1_results['corrupted']['eligible_accepted_terminal'])

    statistic, pvalue = stats.mannwhitneyu(correct_success, corrupted_success, alternative='greater')

    print(f"Statistical Test (Correct > Corrupted):")
    print(f"  Mann-Whitney U test: p = {pvalue:.4f}")
    if pvalue < 0.05:
        print(f"  ✓ Significant at p < 0.05")
    else:
        print(f"  ✗ Not significant")
    print()


    evidence_rq1 = {
        'claim': 'Persistent state errors independently cause wrong decisions & violations',
        'evidence': {
            'correct_vs_corrupted': {
                'correct_rate': metrics['correct']['accepted_terminal_rate'],
                'corrupted_rate': metrics['corrupted']['accepted_terminal_rate'],
                'difference': metrics['correct']['accepted_terminal_rate'] - metrics['corrupted']['accepted_terminal_rate'],
                'p_value': pvalue,
                'significant': pvalue < 0.05
            },
            'corrupted_vs_nomemory': {
                'corrupted_rate': metrics['corrupted']['accepted_terminal_rate'],
                'nomemory_rate': metrics['nomemory']['accepted_terminal_rate'],
                'corrupted_worse': metrics['corrupted']['accepted_terminal_rate'] < metrics['nomemory']['accepted_terminal_rate'],
                'interpretation': 'Wrong state is worse than no state' if metrics['corrupted']['accepted_terminal_rate'] < metrics['nomemory']['accepted_terminal_rate'] else 'Inconclusive'
            }
        },
        'conclusion': 'SUPPORTED' if pvalue < 0.05 and metrics['corrupted']['accepted_terminal_rate'] < metrics['nomemory']['accepted_terminal_rate'] else 'WEAK'
    }
else:
    evidence_rq1 = {'conclusion': 'INCOMPLETE', 'reason': 'Missing experiment results'}

print()


print("EXPERIMENT 2: Permission Layer Insufficiency (RQ2)")
print("-"*120)
print("Claim: Action-layer permission alone cannot solve state errors")
print()

exp2_path = EXPERIMENTS_DIR / "exp2-permission-layer-gpt56sol" / "pilot_summary.json"

if exp2_path.exists():
    with open(exp2_path) as f:
        exp2_data = json.load(f)


    exp2_results = {arm['arm']: arm for arm in exp2_data['table']}

    print("Violation Rates:")
    print(f"{'Arm':<20} {'Violations':<20} {'Rate':<20}")
    print("-"*120)

    for arm in ['statewise_v1', 'bare', 'rationale', 'plan_approval']:
        if arm in exp2_results:
            data = exp2_results[arm]
            rate = data['eligible_safety_violation'] / data['eligible_episodes']
            print(f"{arm:<20} {data['eligible_safety_violation']:<20} {rate:<20.1%}")

    print()


    statewise_viol = exp2_results['statewise_v1']['eligible_safety_violation'] / exp2_results['statewise_v1']['eligible_episodes']
    baseline_viols = [
        exp2_results[arm]['eligible_safety_violation'] / exp2_results[arm]['eligible_episodes']
        for arm in ['bare', 'rationale', 'plan_approval']
        if arm in exp2_results
    ]

    evidence_rq2 = {
        'claim': 'Action-layer permission alone cannot solve state errors',
        'evidence': {
            'statewise_violations': statewise_viol,
            'baseline_violations': {
                'bare': baseline_viols[0] if len(baseline_viols) > 0 else None,
                'rationale': baseline_viols[1] if len(baseline_viols) > 1 else None,
                'plan_approval': baseline_viols[2] if len(baseline_viols) > 2 else None,
            },
            'statewise_better': all(statewise_viol < v for v in baseline_viols),
            'baselines_still_high': all(v > 0.15 for v in baseline_viols)
        },
        'conclusion': 'SUPPORTED' if all(statewise_viol < v for v in baseline_viols) and all(v > 0.15 for v in baseline_viols) else 'WEAK'
    }
else:
    evidence_rq2 = {'conclusion': 'INCOMPLETE', 'reason': 'Missing experiment results'}

print()


print("EXPERIMENT 3: StateWise Core Performance (RQ3)")
print("-"*120)
print("Claim: StateWise reduces violations while preserving capability")
print()

exp3_results = {}
for arm in ['statewise', 'safetysentry']:
    run_dir = EXPERIMENTS_DIR / f"exp3-{arm}-224-gpt56sol"
    summary_path = run_dir / "pilot_summary.json"

    if summary_path.exists():
        with open(summary_path) as f:
            data = json.load(f)
            exp3_results[arm] = data['table'][0]
            print(f"✓ Loaded {arm}: {exp3_results[arm]['episodes']} episodes")
    else:
        print(f"✗ Missing {arm}: {summary_path}")

print()

if len(exp3_results) == 2:
    print("Safety vs Capability Trade-off:")
    print(f"{'Arm':<20} {'Violations':<20} {'Accepted Terminal':<20} {'Balance':<20}")
    print("-"*120)

    for arm in ['statewise', 'safetysentry']:
        data = exp3_results[arm]
        viol_rate = data['eligible_safety_violation'] / data['eligible_episodes']
        accept_rate = data['eligible_accepted_terminal'] / data['eligible_episodes']
        balance = accept_rate * (1 - viol_rate)

        print(f"{arm:<20} {viol_rate:<20.1%} {accept_rate:<20.1%} {balance:<20.3f}")

    print()


    statewise_viol = exp3_results['statewise']['eligible_safety_violation'] / exp3_results['statewise']['eligible_episodes']
    statewise_accept = exp3_results['statewise']['eligible_accepted_terminal'] / exp3_results['statewise']['eligible_episodes']
    sentry_viol = exp3_results['safetysentry']['eligible_safety_violation'] / exp3_results['safetysentry']['eligible_episodes']
    sentry_accept = exp3_results['safetysentry']['eligible_accepted_terminal'] / exp3_results['safetysentry']['eligible_episodes']

    evidence_rq3 = {
        'claim': 'StateWise reduces violations while preserving capability',
        'evidence': {
            'statewise': {
                'violations': statewise_viol,
                'capability': statewise_accept,
                'safe_and_capable': statewise_viol < 0.15 and statewise_accept > 0.60
            },
            'safetysentry': {
                'violations': sentry_viol,
                'capability': sentry_accept,
                'too_conservative': sentry_accept < 0.50
            },
            'statewise_better_balance': (statewise_accept > sentry_accept) and (statewise_viol < 0.15)
        },
        'conclusion': 'SUPPORTED' if (statewise_viol < 0.15 and statewise_accept > 0.60 and statewise_accept > sentry_accept) else 'WEAK'
    }
else:
    evidence_rq3 = {'conclusion': 'INCOMPLETE', 'reason': 'Missing experiment results'}

print()


report = {
    'RQ1': evidence_rq1,
    'RQ2': evidence_rq2,
    'RQ3': evidence_rq3,
    'generated_at': pd.Timestamp.now().isoformat()
}

output_path = PROJECT_ROOT / 'paper_experiments' / "analysis" / "claim_evidence_report.json"
output_path.parent.mkdir(parents=True, exist_ok=True)

with open(output_path, 'w') as f:
    json.dump(report, f, indent=2)

print("="*120)
print("CLAIM-EVIDENCE SUMMARY")
print("="*120)
print()

for rq, evidence in [('RQ1', evidence_rq1), ('RQ2', evidence_rq2), ('RQ3', evidence_rq3)]:
    status = evidence.get('conclusion', 'UNKNOWN')
    icon = '✓' if status == 'SUPPORTED' else '⚠' if status == 'WEAK' else '✗'
    print(f"{icon} {rq}: {status}")
    if 'claim' in evidence:
        print(f"   {evidence['claim']}")
    print()

print(f"Full report exported to: {output_path}")
print("="*120)
