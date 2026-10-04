from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from scaffold.runners import method_freeze
from scaffold.runners.run_episode_real import _preflight, _write_atomic
from scaffold.statewise import config
from scaffold.statewise.agents import llm_client
from scaffold.statewise.evaluation import case_schema, failure_taxonomy
from scaffold.statewise.runtime import lightweight_runtime


SCAFFOLD_DIR = Path(__file__).resolve().parent.parent
CASES_DIR = SCAFFOLD_DIR / "cases"
PROJECT_DIR = SCAFFOLD_DIR.parent
DEFAULT_PHASE = "diagnostic_round_1"


def _load_cases(case_ids, phase):
    wanted = set(case_ids or [])
    selected = []
    for path in sorted(CASES_DIR.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        if wanted:
            if case.get("case_id") not in wanted:
                continue
        elif case.get("phase") != phase:
            continue
        if case.get("execution", {}).get("tier") != "lightweight":
            continue
        selected.append((path, case))
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--phase", default=DEFAULT_PHASE)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_DIR / "runs" / "diagnostic_triads"),
    )
    args = parser.parse_args()

    if config.FAKE_API:
        print("STATECLARIFY_FAKE_API must be false for a live diagnostic run", file=sys.stderr)
        return 2
    if args.trials < 1:
        print("--trials must be positive", file=sys.stderr)
        return 2

    freeze = method_freeze.verify()
    if not freeze["valid"]:
        print(
            "StateWise-v0 freeze mismatch; create a named variant or restore the baseline",
            file=sys.stderr,
        )
        print(json.dumps(freeze, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    cases = _load_cases(args.case_ids, args.phase)
    if not cases:
        print("No matching executable diagnostic cases", file=sys.stderr)
        return 2
    schema_failures = {
        case["case_id"]: case_schema.validate_case(case)
        for _, case in cases
        if case_schema.validate_case(case)
    }
    if schema_failures:
        print(json.dumps(schema_failures, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    started = datetime.now(timezone.utc)
    destination = Path(args.output_dir) / (
        f"diagnostic-triads-{started.strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    preflight = _preflight()
    print(
        f"preflight ok={preflight['ok']} seconds={preflight['wall_seconds']} "
        f"model={config.MODEL_NAME}",
        flush=True,
    )

    records = []
    arm_records = []
    statuses = Counter()
    measurement_errors = []

    def manifest(complete):
        now = datetime.now(timezone.utc)
        return {
            "kind": "statewise_v0_live_diagnostic_triads",
            "schema_version": failure_taxonomy.SCHEMA_VERSION,
            "complete": complete,
            "started_at": started.isoformat(),
            "updated_at": now.isoformat(),
            "finished_at": now.isoformat() if complete else None,
            "elapsed_seconds": (now - started).total_seconds(),
            "model": config.MODEL_NAME,
            "method_freeze": freeze,
            "preflight": preflight,
            "selected_case_ids": [case["case_id"] for _, case in cases],
            "trials": args.trials,
            "status_counts": dict(statuses),
            "measurement_errors": measurement_errors,
            "failure_taxonomy": failure_taxonomy.aggregate(arm_records),
            "arm_records": arm_records,
            "records": records,
        }

    if not preflight["ok"]:
        _write_atomic(destination, manifest(complete=True))
        print(f"manifest={destination.resolve()}", flush=True)
        return 2

    for path, case in cases:
        for trial in range(args.trials):
            print(f"[{case['case_id']} trial={trial}] Correct/Corrupted/Mitigated", flush=True)
            llm_client.reset_call_metrics()
            try:
                evaluation = lightweight_runtime.run_executable_conditions(str(path))
                coherence = evaluation.get("contracts", {}).get("runtime_coherence", {})
                if not coherence.get("valid", False):
                    measurement_errors.append({
                        "case_id": case["case_id"],
                        "trial": trial,
                        "type": "F.reset_scope_contamination",
                        "detail": coherence,
                    })


                record_payload = {
                    "case_id": case["case_id"],
                    "trial": trial,
                    "runtime_contract": evaluation.get("runtime_contract"),
                    "contracts": evaluation.get("contracts"),
                    "normalized_arms": [],
                    "raw_evaluation": evaluation,
                }
                records.append(record_payload)
                normalized = []
                for condition in ("correct", "corrupted", "mitigated"):
                    result = evaluation["arms"][condition]
                    try:
                        arm_record = failure_taxonomy.build_arm_record(
                            case,
                            condition,
                            result,
                            method_version=freeze["version"],
                            method_fingerprint=freeze["actual_fingerprint"],
                            api_call_metrics=evaluation.get(
                                "arm_api_call_metrics", {}
                            ).get(condition, []),
                        )
                    except Exception as exc:
                        measurement_errors.append({
                            "case_id": case["case_id"],
                            "trial": trial,
                            "condition": condition,
                            "type": "F.evaluator",
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        })
                        print(
                            f"  {condition}: LOGGER_ERROR {type(exc).__name__}: {exc}",
                            flush=True,
                        )
                        continue
                    normalized.append(arm_record)
                    arm_records.append(arm_record)
                    episode = arm_record["episode"]
                    outcome = (
                        "TASK_COMPLETED"
                        if episode["task_success"]
                        else "SAFE_TERMINAL"
                        if episode["acceptable_safe_terminal"]
                        else episode["status"] or "UNKNOWN"
                    )
                    statuses[f"{condition}::{outcome}"] += 1
                    print(
                        f"  {condition}: status={episode['status']} "
                        f"task={episode['task_success']} safe={not episode['safety_violation']} "
                        f"steps={episode['steps']} labels={arm_record['failure_labels']}",
                        flush=True,
                    )
                record_payload["normalized_arms"] = normalized
            except Exception as exc:
                measurement_errors.append({
                    "case_id": case["case_id"],
                    "trial": trial,
                    "type": "F.runtime",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                })
                print(f"  ERROR {type(exc).__name__}: {exc}", flush=True)
            _write_atomic(destination, manifest(complete=False))

    _write_atomic(destination, manifest(complete=True))
    print(f"manifest={destination.resolve()}")
    print(
        "taxonomy="
        + json.dumps(
            failure_taxonomy.aggregate(arm_records),
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )


    return 1 if measurement_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
