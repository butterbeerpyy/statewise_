
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "================================================================================"
echo "Running P0 Experiments - Core Claims"
echo "================================================================================"
echo ""

API_PROFILE="api_02"  
CONDA_ENV="statewise"

DATASET_42="$PROJECT_ROOT/scaffold/experiments/test_set_42_v1.json"
DATASET_224="$PROJECT_ROOT/scaffold/experiments/statewise_current_pool_v1.json"

OUTPUT_DIR="$PROJECT_ROOT/runs/paper_experiments"
mkdir -p "$OUTPUT_DIR"

echo "Configuration:"
echo "  API Profile: $API_PROFILE (gpt-5.6-sol)"
echo "  42-case dataset: $DATASET_42"
echo "  224-case dataset: $DATASET_224"
echo "  Output: $OUTPUT_DIR"
echo ""

if [ ! -f "$DATASET_42" ]; then
    echo "ERROR: 42-case dataset not found: $DATASET_42"
    echo "Please run dataset preparation first."
    exit 1
fi

if [ ! -f "$DATASET_224" ]; then
    echo "ERROR: 224-case dataset not found: $DATASET_224"
    echo "Please run dataset preparation first."
    exit 1
fi

echo "================================================================================"
echo "Experiment 1: State Corruption Impact (RQ1)"
echo "================================================================================"
echo "Claim: Persistent state errors independently cause wrong decisions & violations"
echo "Arms: Correct / Corrupted / NoMemory"
echo "Dataset: 42 eligible cases"
echo "Estimated time: ~15-20 hours (parallel)"
echo ""

read -p "Run Experiment 1? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Starting Experiment 1..."

    conda run -n "$CONDA_ENV" --no-capture-output \
        python -m scaffold.runners.run_managed_pilot \
        --run-id exp1-correct-gpt56sol \
        --snapshot "$DATASET_42" \
        --arm correct \
        --trials 1 \
        --api-profile "$API_PROFILE" \
        --max-attempts 3 \
        2>&1 | tee "$OUTPUT_DIR/exp1_correct.log" &
    PID_CORRECT=$!

    conda run -n "$CONDA_ENV" --no-capture-output \
        python -m scaffold.runners.run_managed_pilot \
        --run-id exp1-corrupted-gpt56sol \
        --snapshot "$DATASET_42" \
        --arm corrupted \
        --trials 1 \
        --api-profile "$API_PROFILE" \
        --max-attempts 3 \
        2>&1 | tee "$OUTPUT_DIR/exp1_corrupted.log" &
    PID_CORRUPTED=$!

    conda run -n "$CONDA_ENV" --no-capture-output \
        python -m scaffold.runners.run_managed_pilot \
        --run-id exp1-nomemory-gpt56sol \
        --snapshot "$DATASET_42" \
        --arm no_memory \
        --trials 1 \
        --api-profile "$API_PROFILE" \
        --max-attempts 3 \
        2>&1 | tee "$OUTPUT_DIR/exp1_nomemory.log" &
    PID_NOMEMORY=$!

    echo "Experiment 1 running in background:"
    echo "  Correct: PID $PID_CORRECT"
    echo "  Corrupted: PID $PID_CORRUPTED"
    echo "  NoMemory: PID $PID_NOMEMORY"
    echo ""
    echo "Waiting for completion..."
    wait $PID_CORRECT $PID_CORRUPTED $PID_NOMEMORY
    echo "Experiment 1 complete!"
    echo ""
fi

echo "================================================================================"
echo "Experiment 2: Permission Layer Insufficiency (RQ2)"
echo "================================================================================"
echo "Claim: Action-layer permission alone cannot solve state errors"
echo "Arms: StateWise v1 / Bare / Rationale / PlanApproval"
echo "Dataset: 42 eligible cases"
echo "Estimated time: ~20-30 hours"
echo ""

read -p "Run Experiment 2? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Starting Experiment 2..."

    conda run -n "$CONDA_ENV" --no-capture-output \
        python -m scaffold.runners.run_managed_pilot \
        --run-id exp2-permission-layer-gpt56sol \
        --snapshot "$DATASET_42" \
        --arm statewise_v1,bare,rationale,plan_approval \
        --trials 1 \
        --api-profile "$API_PROFILE" \
        --max-attempts 3 \
        2>&1 | tee "$OUTPUT_DIR/exp2_permission_layer.log"

    echo "Experiment 2 complete!"
    echo ""
fi

echo "================================================================================"
echo "Experiment 3: StateWise Core Performance (RQ3)"
echo "================================================================================"
echo "Claim: StateWise reduces violations while preserving capability"
echo "Arms: StateWise v1 / SafetySentry"
echo "Dataset: 224 full cases"
echo "Estimated time: ~50-70 hours"
echo ""

read -p "Run Experiment 3? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Starting Experiment 3..."

    conda run -n "$CONDA_ENV" --no-capture-output \
        python -m scaffold.runners.run_managed_pilot \
        --run-id exp3-statewise-224-gpt56sol \
        --snapshot "$DATASET_224" \
        --arm statewise_v1 \
        --trials 1 \
        --api-profile "$API_PROFILE" \
        --max-attempts 3 \
        2>&1 | tee "$OUTPUT_DIR/exp3_statewise.log" &
    PID_STATEWISE=$!

    conda run -n "$CONDA_ENV" --no-capture-output \
        python -m scaffold.runners.run_managed_pilot \
        --run-id exp3-safetysentry-224-gpt56sol \
        --snapshot "$DATASET_224" \
        --arm safety_sentry \
        --trials 1 \
        --api-profile "$API_PROFILE" \
        --max-attempts 3 \
        2>&1 | tee "$OUTPUT_DIR/exp3_safetysentry.log" &
    PID_SENTRY=$!

    echo "Experiment 3 running in background:"
    echo "  StateWise: PID $PID_STATEWISE"
    echo "  SafetySentry: PID $PID_SENTRY"
    echo ""
    echo "Waiting for completion..."
    wait $PID_STATEWISE $PID_SENTRY
    echo "Experiment 3 complete!"
    echo ""
fi

echo "================================================================================"
echo "P0 Experiments Complete!"
echo "================================================================================"
echo ""
echo "Next steps:"
echo "  1. Run analysis: python paper_experiments/analysis/analyze_p0_results.py"
echo "  2. Generate report: python paper_experiments/analysis/generate_claim_evidence_report.py"
echo "  3. Optional: Run P1 experiments (ablation) with run_p1_experiments.sh"
echo ""
echo "Results location: $OUTPUT_DIR"
echo "================================================================================"
