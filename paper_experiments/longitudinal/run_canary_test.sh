
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "================================================================================"
echo "Longitudinal Experiment - Canary Test"
echo "================================================================================"
echo ""

API_PROFILE="api_02"
CONDA_ENV="statewise"

SEQ_DIR="$PROJECT_ROOT/paper_experiments/longitudinal/sequences"
SEQUENCES=(
    "$SEQ_DIR/seq_env_project_env_001.json"
)

METHODS=("statewise_v1" "rationale" "oracle")

OUTPUT_DIR="$PROJECT_ROOT/paper_experiments/longitudinal/results/canary"
mkdir -p "$OUTPUT_DIR"

echo "Configuration:"
echo "  API Profile: $API_PROFILE"
echo "  Sequences: ${#SEQUENCES[@]}"
echo "  Methods: ${METHODS[@]}"
echo "  Output: $OUTPUT_DIR"
echo ""

echo "Checking sequences..."
for seq in "${SEQUENCES[@]}"; do
    if [ ! -f "$seq" ]; then
        echo "  ✗ Missing: $seq"
        exit 1
    else
        echo "  ✓ Found: $(basename $seq)"
    fi
done
echo ""

echo "================================================================================"
echo "Running Canary Test"
echo "================================================================================"
echo "This will run:"
echo "  ${#SEQUENCES[@]} sequences × ${#METHODS[@]} methods × 1 run"
echo "  = $((${#SEQUENCES[@]} * ${#METHODS[@]})) total runs"
echo "  Estimated time: 1-2 hours"
echo ""

read -p "Continue? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""
echo "Starting canary test..."
echo ""

conda run -n "$CONDA_ENV" --no-capture-output \
    python "$PROJECT_ROOT/paper_experiments/runners/run_longitudinal_experiment.py" \
    --sequences "${SEQUENCES[@]}" \
    --methods "${METHODS[@]}" \
    --output-dir "$OUTPUT_DIR" \
    --api-profile "$API_PROFILE" \
    --runs 1 \
    2>&1 | tee "$OUTPUT_DIR/canary_test.log"

echo ""
echo "================================================================================"
echo "Canary Test Complete!"
echo "================================================================================"
echo ""

SUMMARY_FILE="$OUTPUT_DIR/longitudinal_summary.json"

if [ -f "$SUMMARY_FILE" ]; then
    echo "✓ Summary generated: $SUMMARY_FILE"

    echo ""
    echo "Quick Analysis:"
    python3 << EOF
import json
with open('$SUMMARY_FILE') as f:
    data = json.load(f)

print(f"  Total runs: {len(data['results'])}")
print(f"  Methods tested: {', '.join(data['methods'])}")
print("")

by_method = {}
for result in data['results']:
    method = result['method']
    if method not in by_method:
        by_method[method] = {
            'cumulative_questions': [],
            'state_reuse_rate': [],
            'success_rate': []
        }

    metrics = result['sequence_metrics']
    by_method[method]['cumulative_questions'].append(metrics['cumulative_human_questions'])
    by_method[method]['state_reuse_rate'].append(metrics['state_reuse_rate'])
    by_method[method]['success_rate'].append(metrics['successful_task_rate'])

print("Method Comparison:")
print(f"{'Method':<20} {'Avg Questions':<20} {'Avg State Reuse':<20} {'Avg Success':<20}")
print("-" * 80)

for method in sorted(by_method.keys()):
    stats = by_method[method]
    avg_q = sum(stats['cumulative_questions']) / len(stats['cumulative_questions'])
    avg_reuse = sum(stats['state_reuse_rate']) / len(stats['state_reuse_rate'])
    avg_success = sum(stats['success_rate']) / len(stats['success_rate'])

    print(f"{method:<20} {avg_q:<20.1f} {avg_reuse:<20.1%} {avg_success:<20.1%}")

print("")

statewise_q = sum(by_method.get('statewise_v1', {}).get('cumulative_questions', [0])) / len(by_method.get('statewise_v1', {}).get('cumulative_questions', [1]))
rationale_q = sum(by_method.get('rationale', {}).get('cumulative_questions', [0])) / len(by_method.get('rationale', {}).get('cumulative_questions', [1]))

if 'statewise_v1' in by_method and 'rationale' in by_method:
    if statewise_q < rationale_q:
        print("✓ StateWise has fewer cumulative questions than Rationale (expected)")
    else:
        print("⚠ StateWise does NOT have fewer questions - check implementation")
    print("")
EOF

else
    echo "✗ Summary file not found: $SUMMARY_FILE"
    echo "   Check logs for errors"
fi

echo ""
echo "Next steps:"
echo "  1. Review results in: $OUTPUT_DIR"
echo "  2. Check logs for any issues"
echo "  3. If canary passes, run full experiment with run_longitudinal_full.sh"
echo ""
echo "================================================================================"
