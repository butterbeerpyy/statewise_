from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import glob
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from scaffold.statewise import config
from scaffold.statewise.agents import llm_client
from scaffold.statewise.evaluation import evaluation_levels, grading
from scaffold.statewise.runtime import lightweight_runtime


SCAFFOLD_DIR = Path(__file__).resolve().parent.parent
CASES_DIR = SCAFFOLD_DIR / "cases"
PROJECT_DIR = SCAFFOLD_DIR.parent


def _algorithm_fingerprint():

    digest = hashlib.sha256()
    source_root = SCAFFOLD_DIR / "statewise"
    for path in sorted(source_root.rglob("*.py")):
        digest.update(path.relative_to(source_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _write_atomic(destination, payload):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.tmp"
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, destination)


def _preflight():

    llm_client.reset_call_metrics()
    started = time.perf_counter()
    try:
        response = llm_client.chat(
            stage="episode_real:preflight",
            messages=[{
                "role": "user",
                "content": 'Return only this JSON object: {"api_ready": true}',
            }],
        )
        return {
            "ok": response.get("api_ready") is True,
            "wall_seconds": round(time.perf_counter() - started, 4),
            "calls": llm_client.get_call_metrics(),
        }
    except Exception as exc:
        return {
            "ok": False,
            "wall_seconds": round(time.perf_counter() - started, 4),
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "calls": llm_client.get_call_metrics(),
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument(
        "--output-dir", default=str(PROJECT_DIR / "runs" / "episode_real")
    )
    args = parser.parse_args()

    if config.FAKE_API:
        print("STATECLARIFY_FAKE_API must be false for a live episode run", file=sys.stderr)
        return 2

    paths = sorted(glob.glob(str(CASES_DIR / "*.json")))
    cases = []
    wanted = set(args.case_ids or [])
    for path in paths:
        case = json.loads(Path(path).read_text(encoding="utf-8"))
        if wanted and case.get("case_id") not in wanted:
            continue
        if case.get("execution", {}).get("tier") == "lightweight":
            cases.append((path, case))
    if not cases:
        print("No matching executable lightweight cases", file=sys.stderr)
        return 2

    started = datetime.now(timezone.utc)
    output_dir = Path(args.output_dir)
    destination = output_dir / f"episode-real-{started.strftime('%Y%m%dT%H%M%SZ')}.json"
    algorithm_fingerprint = _algorithm_fingerprint()
    preflight = _preflight()
    print(
        f"preflight ok={preflight['ok']} seconds={preflight['wall_seconds']} "
        f"model={config.MODEL_NAME}",
        flush=True,
    )
    if not preflight["ok"]:
        finished = datetime.now(timezone.utc)
        _write_atomic(destination, {
            "kind": "live_api_executable_episode",
            "evaluation_layers": ["decision", "transition", "episode"],
            "complete": True,
            "started_at": started.isoformat(),
            "updated_at": finished.isoformat(),
            "finished_at": finished.isoformat(),
            "elapsed_seconds": (finished - started).total_seconds(),
            "model": config.MODEL_NAME,
            "algorithm_fingerprint": algorithm_fingerprint,
            "preflight": preflight,
            "status_counts": {},
            "records": [],
        })
        print(
            f"API preflight failed: {preflight.get('error_type', 'invalid_json_contract')} "
            f"{preflight.get('error', '')}",
            file=sys.stderr,
        )
        return 2
    records = []
    statuses = Counter()
    hard_failure = False

    def checkpoint(complete=False):
        now = datetime.now(timezone.utc)
        _write_atomic(destination, {
            "kind": "live_api_executable_episode",
            "evaluation_layers": ["decision", "transition", "episode"],
            "complete": complete,
            "started_at": started.isoformat(),
            "updated_at": now.isoformat(),
            "finished_at": now.isoformat() if complete else None,
            "elapsed_seconds": (now - started).total_seconds(),
            "model": config.MODEL_NAME,
            "algorithm_fingerprint": algorithm_fingerprint,
            "preflight": preflight,
            "status_counts": dict(statuses),
            "records": records,
        })

    for path, case in cases:
        expected = case.get("expected", {}).get("corrupted", {})
        decision_expected = expected.get("decision", expected)
        for trial in range(args.trials):
            print(f"[{case['case_id']} trial={trial}] executable episode", flush=True)
            llm_client.reset_call_metrics()
            try:
                result = lightweight_runtime.run_executable_case(
                    path, condition="corrupted"
                )
                result["grade"] = grading.grade_result(
                    result, case, decision_expected, enable_llm_judge=False
                )
                levels = evaluation_levels.evaluate(result, result["grade"])
                result["evaluation_levels"] = levels
                episode = levels["episode"]
                statuses[episode.get("terminal_outcome") or episode.get("status")] += 1
                hard_failure = hard_failure or episode["safety_violation"] or episode.get("status") in {
                    "TASK_FAILURE", "STEP_LIMIT"
                }
                records.append(
                    {
                        "case_id": case["case_id"],
                        "trial": trial,
                        "api_call_metrics": llm_client.get_call_metrics(),
                        "evaluation_levels": levels,
                        "result": result,
                    }
                )
                print(
                    f"  status={episode['status']} outcome={episode['terminal_outcome']} "
                    f"task_success={episode['task_success']} "
                    f"safe_terminal={episode['acceptable_safe_terminal']} "
                    f"safety_violation={episode['safety_violation']} steps={episode['steps']}",
                    flush=True,
                )
            except Exception as exc:
                hard_failure = True
                records.append(
                    {
                        "case_id": case["case_id"],
                        "trial": trial,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "api_call_metrics": llm_client.get_call_metrics(),
                    }
                )
                print(f"  ERROR {type(exc).__name__}: {exc}", flush=True)


            checkpoint(complete=False)

    checkpoint(complete=True)
    print(f"manifest={destination.resolve()}")
    return 1 if hard_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
