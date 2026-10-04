from __future__ import annotations

import argparse
from datetime import datetime, timezone
import glob
import json
import os
from pathlib import Path
import sys

from scaffold.statewise import config
from scaffold.statewise.evaluation import case_eval


SCAFFOLD_DIR = Path(__file__).resolve().parent.parent
CASES_DIR = SCAFFOLD_DIR / "cases"
PROJECT_DIR = SCAFFOLD_DIR.parent


def _action_text(action):
    if not action:
        return "<none>"
    arguments = json.dumps(action.get("arguments", {}), ensure_ascii=False, sort_keys=True)
    target = action.get("target")
    suffix = f" target={target}" if target is not None else ""
    return f"{action.get('tool')}.{action.get('operation')} {arguments}{suffix}"


def _compact_arm(arm):
    rounds = []
    for item in arm.get("inspection_rounds", []):
        rounds.append(
            {
                "cycle": item.get("cycle"),
                "action": item.get("action"),
                "rationale": item.get("rationale"),
                "impact": item.get("impact"),
                "support_states": item.get("support_states", []),
                "critical_states": item.get("critical_states", []),
                "routing_decisions": item.get("routing_decisions", []),
                "attribution_metrics": item.get("attribution_metrics", {}),
            }
        )
    runtime = arm.get("runtime_execution")
    return {
        "initial_action": arm.get("initial_action"),
        "inspection_rounds": rounds,
        "questions_asked": arm.get("questions_asked", []),
        "human_interactions": arm.get("human_interactions", []),
        "replan_count": arm.get("replan_count"),
        "final_action": arm.get("final_action"),
        "residual_gate": arm.get("residual_gate"),
        "grade": arm.get("grade", {}),
        "runtime_execution": runtime,
        "has_executable_trajectory": bool(runtime and runtime.get("trajectory")),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_DIR / "runs" / "debug_real_paths"),
    )
    args = parser.parse_args()

    if config.FAKE_API:
        print("STATECLARIFY_FAKE_API must be false for this live diagnostic", file=sys.stderr)
        return 2

    paths = sorted(glob.glob(str(CASES_DIR / "*.json")))
    if args.case_ids:
        wanted = set(args.case_ids)
        paths = [path for path in paths if Path(path).stem in wanted]
    if not paths:
        print("No matching cases", file=sys.stderr)
        return 2

    started = datetime.now(timezone.utc)
    records = []
    for path in paths:
        case = json.loads(Path(path).read_text(encoding="utf-8"))
        case_id = case["case_id"]
        print(f"[{case_id}] evaluating", flush=True)
        try:
            results, failures = case_eval.evaluate_case(path, case, enable_llm_judge=False)
            primary = (
                results.get("experimental_conditions", {}).get("mitigated")
                or results.get("corrupted")
                or results.get("single", {})
            )
            compact = _compact_arm(primary)
            records.append(
                {
                    "case_id": case_id,
                    "case_path": str(Path(path).resolve()),
                    "failures": failures,
                    "primary_path": compact,
                    "experimental_contracts": results.get("experimental_contracts", {}),
                    "full_results": results,
                }
            )
            grade = compact["grade"]
            print(
                f"[{case_id}] {_action_text(compact['initial_action'])} -> "
                f"{_action_text(compact['final_action'])} -> "
                f"gate={compact['residual_gate'].get('decision') if compact['residual_gate'] else None} "
                f"status={grade.get('task_status')} executable_trace={compact['has_executable_trajectory']}",
                flush=True,
            )
        except Exception as exc:
            records.append(
                {
                    "case_id": case_id,
                    "case_path": str(Path(path).resolve()),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            print(f"[{case_id}] ERROR {type(exc).__name__}: {exc}", flush=True)

    finished = datetime.now(timezone.utc)
    manifest = {
        "kind": "live_api_path_diagnostic",
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "elapsed_seconds": (finished - started).total_seconds(),
        "model": config.MODEL_NAME,
        "fake_api": config.FAKE_API,
        "records": records,
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    destination = output_dir / f"debug-real-paths-{stamp}.json"
    temporary = output_dir / f".{destination.name}.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, destination)
    print(f"manifest={destination.resolve()}")
    return 0 if all("error" not in item for item in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
