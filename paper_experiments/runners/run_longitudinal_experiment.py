import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any


PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scaffold.statewise import config
from scaffold.statewise.core import main_loop
from scaffold.statewise.memory import memory_store
from scaffold.statewise.evaluation import case_eval


def load_sequence(sequence_path: str) -> Dict:

    with open(sequence_path) as f:
        return json.load(f)


def initialize_corrupted_memory(shared_state: Dict) -> None:

    memory_store.reset()


    memory_store.add_memory(
        memory_id=shared_state['memory_id'],
        key=shared_state['memory_key'],
        value=shared_state['corrupted_value'],
        scope=shared_state['scope'],
        confidence='high',
        source='injected_corruption'
    )


def check_state_retrieval(task_result: Dict, memory_key: str) -> bool:

    routing_decisions = task_result.get('routing_decisions', [])

    for decision in routing_decisions:
        if decision.get('method') == 'MEMORY_RETRIEVAL':
            retrieved_keys = decision.get('retrieved_keys', [])
            if memory_key in retrieved_keys:
                return True

    return False


def check_state_correctness(task_result: Dict, memory_key: str, expected_value: Any) -> bool:

    attributed_memories = task_result.get('attributed_memories', [])

    for mem in attributed_memories:
        if mem.get('key') == memory_key and mem.get('value') == expected_value:
            return True

    return False


def check_repeated_question(task_result: Dict, memory_key: str) -> bool:

    user_interactions = task_result.get('user_interactions', [])

    for interaction in user_interactions:
        if interaction.get('type') == 'ASK_STATE':
            if memory_key in str(interaction.get('content', '')).lower():
                return True

    return False


def count_unsafe_mutations(task_result: Dict) -> int:

    oracle = task_result.get('runtime_execution', {}).get('oracle', {})
    violations = oracle.get('violations', [])
    return len([v for v in violations if 'forbidden' in v.lower()])


def count_unnecessary_mutations(task_result: Dict) -> int:

    unnecessary_rate = task_result.get('unnecessary_mutation_rate', 0)
    mutation_count = task_result.get('mutation_count', 0)
    return int(unnecessary_rate * mutation_count)


def run_single_task(
    sequence_id: str,
    task: Dict,
    method: str,
    api_profile: str,
    memory_persistent: Any
) -> Dict:


    case = {
        'case_id': f"{sequence_id}_{task['task_id']}",
        'task': task['prompt'],
        'oracle': task.get('oracle', {}),
        'workspace_snapshot': task.get('workspace_snapshot'),
        'domain': 'longitudinal_sequence'
    }


    result = case_eval.eval_condition(
        case_path=None,
        case=case,
        condition=method,
        proposed=None,
        enable_llm_judge=False,
        memory_override=memory_persistent
    )

    return result


def evaluate_sequence(sequence_result: Dict, shared_state: Dict) -> Dict:


    tasks = sequence_result['tasks']
    n_tasks = len(tasks)

    if n_tasks == 0:
        return {}


    successful_tasks = sum(1 for t in tasks if t.get('task_success', False))


    t1_repaired = tasks[0].get('memory_repair_performed', False)

    future_tasks = tasks[1:] if n_tasks > 1 else []
    state_reused = sum(1 for t in future_tasks
                       if t['longitudinal_metrics']['state_retrieved'])
    repeated_questions = sum(1 for t in future_tasks
                             if t['longitudinal_metrics']['repeated_question'])

    return {
        'total_tasks': n_tasks,
        'successful_tasks': successful_tasks,
        'successful_task_rate': successful_tasks / n_tasks,


        'state_repaired_in_t1': t1_repaired,
        'state_reused_count': state_reused,
        'state_reuse_rate': state_reused / len(future_tasks) if future_tasks else 0,

        'repeated_questions': repeated_questions,
        'repeated_intervention_rate': repeated_questions / len(future_tasks) if future_tasks else 0,

        'cumulative_human_questions': sequence_result['cumulative_metrics']['human_questions'],
        'cumulative_unsafe_mutations': sequence_result['cumulative_metrics']['unsafe_mutations'],
        'cumulative_unnecessary_mutations': sequence_result['cumulative_metrics']['unnecessary_mutations'],

        'questions_per_task': sequence_result['cumulative_metrics']['human_questions'] / n_tasks,


        'task_metrics': [
            {
                'task_index': t['task_index'],
                'task_id': t['task_id'],
                'success': t.get('task_success', False),
                'questions': t.get('questions', 0),
                'state_retrieved': t['longitudinal_metrics']['state_retrieved'],
                'repeated_question': t['longitudinal_metrics']['repeated_question']
            }
            for t in tasks
        ]
    }


def run_sequence(
    sequence_manifest: Dict,
    method: str,
    api_profile: str = 'api_02',
    verbose: bool = True
) -> Dict:


    if verbose:
        print(f"\n{'='*80}")
        print(f"Running Sequence: {sequence_manifest['sequence_id']}")
        print(f"Method: {method}")
        print(f"Tasks: {len(sequence_manifest['tasks'])}")
        print(f"{'='*80}\n")


    initialize_corrupted_memory(sequence_manifest['shared_state'])


    sequence_result = {
        'sequence_id': sequence_manifest['sequence_id'],
        'method': method,
        'started_at': datetime.utcnow().isoformat() + 'Z',
        'tasks': [],
        'cumulative_metrics': {
            'human_questions': 0,
            'unsafe_mutations': 0,
            'unnecessary_mutations': 0,
            'state_repairs': 0
        }
    }


    for task_idx, task in enumerate(sequence_manifest['tasks']):

        if verbose:
            print(f"Task {task_idx + 1}/{len(sequence_manifest['tasks'])}: {task['task_id']}")


        if sequence_manifest.get('reset_workspace_between_tasks', True):

            pass


        if sequence_manifest.get('reset_agent_context_between_tasks', True):

            pass


        task_result = run_single_task(
            sequence_id=sequence_manifest['sequence_id'],
            task=task,
            method=method,
            api_profile=api_profile,
            memory_persistent=memory_store
        )


        task_result['task_index'] = task_idx + 1
        task_result['task_id'] = task['task_id']
        task_result['longitudinal_metrics'] = {
            'task_index': task_idx + 1,
            'state_retrieved': check_state_retrieval(
                task_result,
                sequence_manifest['shared_state']['memory_key']
            ),
            'state_correct': check_state_correctness(
                task_result,
                sequence_manifest['shared_state']['memory_key'],
                sequence_manifest['shared_state']['ground_truth_value']
            ),
            'repeated_question': check_repeated_question(
                task_result,
                sequence_manifest['shared_state']['memory_key']
            )
        }


        sequence_result['cumulative_metrics']['human_questions'] += task_result.get('questions', 0)
        sequence_result['cumulative_metrics']['unsafe_mutations'] += count_unsafe_mutations(task_result)
        sequence_result['cumulative_metrics']['unnecessary_mutations'] += count_unnecessary_mutations(task_result)

        if task_result.get('memory_repair_performed', False):
            sequence_result['cumulative_metrics']['state_repairs'] += 1

        sequence_result['tasks'].append(task_result)

        if verbose:
            success = '✓' if task_result.get('task_success') else '✗'
            questions = task_result.get('questions', 0)
            print(f"  {success} Success: {task_result.get('task_success')}, Questions: {questions}")


    sequence_result['completed_at'] = datetime.utcnow().isoformat() + 'Z'
    sequence_result['sequence_metrics'] = evaluate_sequence(
        sequence_result,
        sequence_manifest['shared_state']
    )

    if verbose:
        print(f"\nSequence Complete:")
        print(f"  Success Rate: {sequence_result['sequence_metrics']['successful_task_rate']:.1%}")
        print(f"  State Reuse Rate: {sequence_result['sequence_metrics']['state_reuse_rate']:.1%}")
        print(f"  Cumulative Questions: {sequence_result['sequence_metrics']['cumulative_human_questions']}")
        print()

    return sequence_result


def run_longitudinal_experiment(
    sequences: List[str],
    methods: List[str],
    output_dir: str,
    api_profile: str = 'api_02',
    runs: int = 1
):


    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    all_results = []

    print(f"{'='*80}")
    print(f"Longitudinal Experiment")
    print(f"{'='*80}")
    print(f"Sequences: {len(sequences)}")
    print(f"Methods: {methods}")
    print(f"Runs per config: {runs}")
    print(f"Total runs: {len(sequences) * len(methods) * runs}")
    print(f"{'='*80}\n")

    for seq_path in sequences:
        sequence_manifest = load_sequence(seq_path)

        for method in methods:
            for run_idx in range(runs):

                print(f"\n--- Sequence: {sequence_manifest['sequence_id']}, Method: {method}, Run: {run_idx + 1}/{runs} ---")

                result = run_sequence(
                    sequence_manifest=sequence_manifest,
                    method=method,
                    api_profile=api_profile,
                    verbose=True
                )

                result['run_index'] = run_idx + 1
                all_results.append(result)


                result_file = output_path / f"{sequence_manifest['sequence_id']}_{method}_run{run_idx+1}.json"
                with open(result_file, 'w') as f:
                    json.dump(result, f, indent=2)


    summary_file = output_path / 'longitudinal_summary.json'
    with open(summary_file, 'w') as f:
        json.dump({
            'experiment_type': 'longitudinal',
            'sequences_count': len(sequences),
            'methods': methods,
            'runs_per_config': runs,
            'total_runs': len(all_results),
            'results': all_results,
            'generated_at': datetime.utcnow().isoformat() + 'Z'
        }, f, indent=2)

    print(f"\n{'='*80}")
    print(f"Experiment Complete!")
    print(f"Results saved to: {output_path}")
    print(f"{'='*80}")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Run longitudinal experiments (RQ5)')
    parser.add_argument('--sequences', nargs='+', required=True, help='Sequence manifest paths')
    parser.add_argument('--methods', nargs='+', required=True, help='Methods to compare')
    parser.add_argument('--output-dir', required=True, help='Output directory')
    parser.add_argument('--api-profile', default='api_02', help='API profile')
    parser.add_argument('--runs', type=int, default=1, help='Repetitions per config')

    args = parser.parse_args()

    run_longitudinal_experiment(
        sequences=args.sequences,
        methods=args.methods,
        output_dir=args.output_dir,
        api_profile=args.api_profile,
        runs=args.runs
    )
