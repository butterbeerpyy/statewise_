from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import glob
import json
import os
from pathlib import Path

from scaffold.statewise.evaluation import case_schema, evaluation_levels
from scaffold.statewise.runtime import lightweight_runtime


SCAFFOLD_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = SCAFFOLD_DIR.parent


def _comparable_snapshot(snapshot):
    return {
        key: value
        for key, value in snapshot.items()
        if key != "captured_at"
    }


def _run_once(case):
    result = {
        "task": case["task"],
        "case_id": case["case_id"],
        "condition": "closure_smoke",
        "final_action": case["execution"]["smoke_action"],
        "residual_gate": {"decision": "EXECUTE"},
        "routing_decisions": [],
    }
    return lightweight_runtime._execute_result(case, result=result)


def validate(case):
    schema_errors = case_schema.validate_case(case)
    if schema_errors:
        return {
            "case_id": case.get("case_id"),
            "passed": False,
            "schema_errors": schema_errors,
        }

    runs = []
    runtime_error = None
    try:
        for _ in range(2):
            result = _run_once(case)
            runtime = result["runtime_execution"]
            levels = evaluation_levels.evaluate(result)
            runs.append({
                "status": runtime["episode_status"],
                "steps": runtime["steps"],
                "workspace_persisted": runtime["workspace_persisted"],
                "before_snapshot": runtime["before_snapshot"],
                "diff": runtime["diff"],
                "oracle": runtime["oracle"],
                "episode": levels["episode"],
            })
    except Exception as exc:
        runtime_error = {
            "type": type(exc).__name__,
            "message": str(exc)[:500],
        }

    reset_equivalent = (
        len(runs) == 2
        and _comparable_snapshot(runs[0]["before_snapshot"])
        == _comparable_snapshot(runs[1]["before_snapshot"])
    )
    terminal = all(
        run["status"] == "COMPLETE"
        and (
            run["oracle"].get("task_completed")
            or run["oracle"].get("acceptable_terminal")
        )
        for run in runs
    )
    safe = all(not run["oracle"].get("violated") for run in runs)
    no_configuration_errors = all(
        not run["oracle"].get("configuration_errors") for run in runs
    )
    ephemeral = all(not run["workspace_persisted"] for run in runs)
    passed = bool(
        runtime_error is None
        and reset_equivalent
        and terminal
        and safe
        and no_configuration_errors
        and ephemeral
    )
    return {
        "case_id": case["case_id"],
        "passed": passed,
        "schema_errors": schema_errors,
        "runtime_error": runtime_error,
        "reset_equivalent": reset_equivalent,
        "terminal": terminal,
        "safe": safe,
        "no_configuration_errors": no_configuration_errors,
        "workspace_ephemeral": ephemeral,
        "runs": runs,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_DIR / "runs" / "closure"),
    )
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    started = datetime.now(timezone.utc)
    paths = sorted(glob.glob(str(SCAFFOLD_DIR / "cases" / "*.json")))
    executable = []
    symbolic = []
    for path in paths:
        case = json.loads(Path(path).read_text(encoding="utf-8"))
        if case.get("execution", {}).get("tier") == "lightweight":
            executable.append(case)
        else:
            symbolic.append(case["case_id"])

    records = []
    outcomes = Counter()
    for case in executable:
        record = validate(case)
        records.append(record)
        if record["runs"]:
            oracle = record["runs"][0]["oracle"]
            outcome = (
                "TASK_COMPLETED"
                if oracle.get("task_completed")
                else oracle.get("terminal_outcome", "NO_TERMINAL")
            )
        else:
            outcome = "RUNTIME_ERROR"
        outcomes[outcome] += 1
        print(
            f"[{'PASS' if record['passed'] else 'FAIL'}] {record['case_id']} "
            f"reset={record['reset_equivalent']} terminal={record['terminal']} "
            f"safe={record['safe']} outcome={outcome}",
            flush=True,
        )

    finished = datetime.now(timezone.utc)
    passed = sum(record["passed"] for record in records)
    manifest = {
        "kind": "deterministic_pipeline_closure",
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "total_cases": len(paths),
        "executable_cases": len(executable),
        "symbolic_cases": len(symbolic),
        "symbolic_case_ids": symbolic,
        "passed": passed,
        "failed": len(records) - passed,
        "outcomes": dict(outcomes),
        "records": records,
    }
    if not args.no_save:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        destination = output_dir / (
            f"closure-{started.strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        temporary = output_dir / f".{destination.name}.tmp"
        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, destination)
        print(f"manifest={destination.resolve()}")
    print(
        f"summary={passed}/{len(executable)} executable passed; "
        f"{len(paths)} total; {len(symbolic)} symbolic"
    )
    return 0 if passed == len(executable) else 1


if __name__ == "__main__":
    raise SystemExit(main())
