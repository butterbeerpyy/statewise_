import argparse
import json
import os
from pathlib import Path

from scaffold.statewise.runtime import lightweight_runtime
from scaffold.statewise.evaluation import evaluation_levels, grading


SCAFFOLD_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = SCAFFOLD_DIR.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--case",
        default=str(SCAFFOLD_DIR / "cases" / "case_output_dir.json"),
    )
    parser.add_argument(
        "--arm",
        choices=("all", "correct", "corrupted", "mitigated"),
        default="all",
        help="default runs the three experimental arms",
    )
    parser.add_argument(
        "--condition",
        choices=("corrupted", "correct", "no_memory"),
        default=None,
        help="legacy single-StateWise mode; prefer --arm",
    )
    parser.add_argument("--episode-root", default=None)
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_DIR / "runs" / "lightweight"),
        help="directory for the complete JSON run manifest",
    )
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--full", action="store_true", help="print the complete pipeline log")
    args = parser.parse_args()

    selected = args.condition or args.arm
    if selected == "all":
        result = lightweight_runtime.run_executable_conditions(
            args.case, episode_root=args.episode_root
        )
    elif args.condition is not None:
        result = lightweight_runtime.run_executable_case(
            args.case,
            condition=args.condition,
            episode_root=args.episode_root,
        )
    else:
        all_arms = lightweight_runtime.run_executable_conditions(
            args.case, episode_root=args.episode_root
        )
        result = all_arms["arms"][selected]
    if "runtime_execution" in result:
        case = json.loads(Path(args.case).read_text(encoding="utf-8"))
        condition = result.get("memory_condition") or result.get("condition", "corrupted")
        expected = case.get("expected", {}).get(condition, {})
        decision_expected = expected.get("decision", expected)
        result["grade"] = grading.grade_result(result, case, decision_expected)
        result["evaluation_levels"] = evaluation_levels.evaluate(result, result["grade"])
    if not args.no_save:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        run_id = result.get("experiment_id") or result["runtime_execution"]["run_id"]
        destination = output_dir / f"{run_id}.json"
        temporary = output_dir / f".{run_id}.tmp"
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, destination)
        if "runtime_execution" in result:
            result["runtime_execution"]["manifest_path"] = str(destination.resolve())
        else:
            result["manifest_path"] = str(destination.resolve())
    if args.full:
        output = result
    elif "arms" in result:
        output = {
            "case_id": result["case_id"],
            "experiment_id": result["experiment_id"],
            "contract": result["contract"],
            "contracts": result.get("contracts", {}),
            "runtime_contract": result["runtime_contract"],
            "arms": {
                name: {
                    "memory_condition": arm["memory_condition"],
                    "mitigation_enabled": arm["mitigation_enabled"],
                    "initial_action": arm["initial_action"],
                    "final_action": arm["final_action"],
                    "gate": arm["residual_gate"]["decision"],
                    "routing_methods": [item["method"] for item in arm["routing_decisions"]],
                    "runtime_oracle": arm["runtime_execution"]["oracle"],
                }
                for name, arm in result["arms"].items()
            },
            "manifest_path": result.get("manifest_path"),
        }
    else:
        output = {
            "case_id": result["case_id"],
            "condition": result["condition"],
            "routing_methods": [item["method"] for item in result["routing_decisions"]],
            "residual_gate": result["residual_gate"],
            "final_action": result["final_action"],
            "runtime_execution": result["runtime_execution"],
            "evaluation_levels": result["evaluation_levels"],
        }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    primary = result.get("arms", {}).get("mitigated") if "arms" in result else result
    status = (primary or {}).get("runtime_execution", {}).get("episode_status")
    return 1 if status in {"SAFETY_FAILURE", "TASK_FAILURE"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
