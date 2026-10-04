from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V2DEV = ROOT.parent / 'statewise'
BATCH = (
    ROOT / 'paper_experiments/results/rq5/batch-claude-20260806-5domain-canary'
)
STATUS_PATH = BATCH / "paired_analysis" / "PIPELINE_STATUS.json"

MODELS = ("gpt-5.6-sol", "deepseek-v4-pro", "qwen3.7-max")


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


def attrition_pending(output_root: Path) -> list[str]:

    pending = []
    for d in sorted(output_root.glob("rq5v2_attrition_repair_*")):
        if d.is_dir() and not (d / "longitudinal_summary.json").exists():
            pending.append(d.name)
    return pending


def wait_for_attrition(output_root: Path, timeout_min: int) -> dict:

    started = time.time()
    last_report = 0.0
    while True:
        pending = attrition_pending(output_root)
        if not pending:
            return {"waited_minutes": round((time.time() - started) / 60.0, 1),
                    "timed_out": False, "still_pending": []}
        elapsed = (time.time() - started) / 60.0
        if elapsed >= timeout_min:
            log(f"attrition wait timed out after {elapsed:.0f} min; pending={pending}")
            return {"waited_minutes": round(elapsed, 1),
                    "timed_out": True, "still_pending": pending}
        if elapsed - last_report >= 5:
            log(f"waiting on attrition ({elapsed:.0f} min): {pending}")
            last_report = elapsed
        time.sleep(30)


def run(command: list[str], label: str) -> int:
    log(f"START {label}")
    result = subprocess.run(command, cwd=str(ROOT))
    log(f"{'OK   ' if result.returncode == 0 else 'FAIL '} {label} "
        f"(rc={result.returncode})")
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path,
                        default=ROOT / "runs" / "rq5_longitudinal")
    parser.add_argument("--attrition-timeout-min", type=int, default=45)
    parser.add_argument("--skip-attrition-wait", action="store_true")
    parser.add_argument("--skip-matrix", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if not args.execute:
        log("no --execute; nothing will run")
        return 0

    status: dict = {
        "schema_version": "rq5-pipeline-status-v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "stages": {},
    }
    overall_started = time.time()


    if args.skip_attrition_wait:
        status["stages"]["attrition_wait"] = {"skipped": True}
    else:
        log("stage 1: waiting for attrition repair")
        status["stages"]["attrition_wait"] = wait_for_attrition(
            args.output_root, args.attrition_timeout_min
        )


    if args.skip_matrix:
        status["stages"]["trial_matrix"] = {"skipped": True}
    else:
        log("stage 2: pre-registered trial matrix (160 episodes; this is the long one)")
        rc = run(
            [sys.executable, "-m", "scaffold.runners.run_rq5_trial_matrix",
             "--execute"],
            "trial matrix",
        )
        status["stages"]["trial_matrix"] = {"returncode": rc, "skipped": False}


    log("stage 3: paired analysis")
    analysis = {}
    for model in MODELS:
        suffix = "" if model == "gpt-5.6-sol" else f"_{model}"
        out = V2DEV / "runs" / "analysis" / f"rq5_paired{suffix}"

        rc = subprocess.run(
            [sys.executable, "-m", "scaffold.runners.build_rq5_paired_analysis",
             "--runs-root", str(args.output_root),
             "--model", model,
             "--output", str(out)],
            cwd=str(V2DEV),
        ).returncode
        analysis[model] = {"returncode": rc, "output": str(out)}
        log(f"  {model}: rc={rc}")
    status["stages"]["paired_analysis"] = analysis


    log("stage 4: publishing to results batch")
    published = []
    dest = BATCH / "paired_analysis"
    dest.mkdir(parents=True, exist_ok=True)
    for model in MODELS:
        suffix = "" if model == "gpt-5.6-sol" else f"_{model}"
        src = V2DEV / "runs" / "analysis" / f"rq5_paired{suffix}"
        for name in ("rq5_paired_analysis.json", "RQ5_PAIRED_ANALYSIS.md"):
            source = src / name
            if not source.exists():
                continue
            target = dest / (
                name if model == "gpt-5.6-sol"
                else f"{Path(name).stem}_{model}{Path(name).suffix}"
            )
            target.write_bytes(source.read_bytes())
            published.append(target.name)
    matrix_src = ROOT / "scaffold/experiments/rq5_trial_matrix_v1.json"
    if matrix_src.exists():
        (BATCH / "rq5_trial_matrix_v1.json").write_bytes(matrix_src.read_bytes())
        published.append("rq5_trial_matrix_v1.json")
    status["stages"]["publish"] = {"files": sorted(set(published))}

    status["finished_at"] = datetime.now(timezone.utc).isoformat()
    status["total_minutes"] = round((time.time() - overall_started) / 60.0, 1)
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    log(f"pipeline finished in {status['total_minutes']:.0f} min")
    log(f"status: {STATUS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
