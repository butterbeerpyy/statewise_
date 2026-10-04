
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "================================================================================"
echo "Running P1 Experiments - Ablation Studies"
echo "================================================================================"
echo ""

API_PROFILE="api_02"  
CONDA_ENV="statewise"

DATASET_42="$PROJECT_ROOT/scaffold/experiments/test_set_42_v1.json"

OUTPUT_DIR="$PROJECT_ROOT/runs/paper_experiments"
mkdir -p "$OUTPUT_DIR"

echo "Configuration:"
echo "  API Profile: $API_PROFILE (gpt-5.6-sol)"
echo "  Dataset: $DATASET_42"
echo "  Output: $OUTPUT_DIR"
echo ""

echo "================================================================================"
echo "Experiment 4: Attribution & Repair Ablation (RQ4)"
echo "================================================================================"
echo "Claim: State attribution and repair are both essential"
echo "Arms: Oracle / V1 / V1-Attribution / V1-Repair / V1-Counterfactual"
echo "Dataset: 42 eligible cases"
echo "Estimated time: ~25-35 hours"
echo ""

read -p "Run Experiment 4? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Starting Experiment 4..."

    conda run -n "$CONDA_ENV" --no-capture-output \
        python -m scaffold.runners.run_managed_pilot \
        --run-id exp4-ablation-gpt56sol \
        --snapshot "$DATASET_42" \
        --arm oracle,statewise_v1,v1_no_attribution,v1_no_repair,v1_no_counterfactual \
        --trials 1 \
        --api-profile "$API_PROFILE" \
        --max-attempts 3 \
        2>&1 | tee "$OUTPUT_DIR/exp4_ablation.log"

    echo "Experiment 4 complete!"
    echo ""
fi

echo "================================================================================"
echo "P1 Experiments Complete!"
echo "================================================================================"
echo ""
echo "Next steps:"
echo "  1. Run analysis: python paper_experiments/analysis/analyze_p1_results.py"
echo "  2. Generate ablation report: python paper_experiments/analysis/generate_ablation_report.py"
echo "  3. Optional: Run P2 experiments (longitudinal) - requires special setup"
echo ""
echo "Results location: $OUTPUT_DIR"
echo "================================================================================"
