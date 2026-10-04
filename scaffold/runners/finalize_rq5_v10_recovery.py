from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil


ROOT = Path(__file__).resolve().parents[2]
METHOD_ROOT = ROOT.parent / 'statewise'
RUN_ROOT = Path('runs/')
RESULT_ROOT = ROOT / 'paper_experiments/results/rq5'
STATUS = RESULT_ROOT / "RQ5_V10_RECOVERY_STATUS.json"
CANONICAL_STATUS = RESULT_ROOT / "RQ5_V10_MATCHED_STATUS.json"
RUN_IDS = (
    "r5v10_env_saf_b3_recovery1",
    "r5v10_git_saf_b3_recovery1",
    "r5v10_db_saf_b3_recovery1",
)


def load(run_id: str) -> dict | None:
    try:
        return json.loads((RUN_ROOT / run_id / "manifest.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def active() -> set[str]:
    found = set()
    for process in psutil.process_iter(("cmdline",)):
        try:
            command = " ".join(process.info.get("cmdline") or [])
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        for run_id in RUN_IDS:
            if run_id in command:
                found.add(run_id)
    return found


def age_minutes(manifest: dict) -> float:
    updated = datetime.fromisoformat(manifest["updated_at"].replace("Z", "+00:00"))
    return max(0.0, (datetime.now(timezone.utc) - updated).total_seconds() / 60)


def snapshot() -> list[dict]:
    running = active()
    rows = []
    for run_id in RUN_IDS:
        manifest = load(run_id)
        counts = (manifest or {}).get("aggregate", {}).get("status_counts", {})
        rows.append({
            "run_id": run_id,
            "status": (manifest or {}).get("status", "NO_MANIFEST"),
            "succeeded": int(counts.get("SUCCEEDED", 0)),
            "failed": int(counts.get("FAILED_TERMINAL", 0)),
            "age_minutes": round(age_minutes(manifest), 2) if manifest else None,
            "active": run_id in running,
        })
    return rows


def write(path: Path, status: str, rows: list[dict], **extra) -> None:
    path.write_text(json.dumps({
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "runs": rows,
        **extra,
    }, indent=2) + "\n", encoding="utf-8")


def resume(run_id: str) -> int:
    run_dir = RUN_ROOT / run_id
    stdout = (run_dir / "recovery-supervisor.stdout.log").open("ab")
    stderr = (run_dir / "recovery-supervisor.stderr.log").open("ab")
    environment = os.environ.copy()
    environment["STATEWISE_RESUME_ROOT"] = str(METHOD_ROOT)
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scaffold/runners/resume_rq5_supervised.py"),
            "--manifest", str(run_dir / "manifest.json"),
            "--stale-minutes", "180",
            "--check-seconds", "60",
        ],
        cwd=METHOD_ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    stdout.close()
    stderr.close()
    return process.pid


def main() -> int:
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    while True:
        rows = snapshot()
        if any(row["status"] in {"FAILED", "COMPLETE_WITH_FAILURES"} or row["failed"] for row in rows):
            write(STATUS, "BLOCKED_BY_TERMINAL_FAILURE", rows)
            return 2
        if all(row["status"] == "COMPLETE" for row in rows):
            break
        resumed = []
        for row in rows:
            if (
                row["status"] not in {"COMPLETE", "NO_MANIFEST"}
                and not row["active"]
                and row["age_minutes"] is not None
                and row["age_minutes"] >= 5
            ):
                resumed.append({"run_id": row["run_id"], "pid": resume(row["run_id"])})
        write(STATUS, "RUNNING", rows, resumed=resumed)
        time.sleep(60)

    commands = (
        "export_rq5_v10_matched.py",
        "analyze_rq5_v10_paired.py",
        "validate_rq5_v10_matched.py",
        "export_paper_resource_costs.py",
    )
    for script in commands:
        subprocess.run(
            [sys.executable, str(ROOT / "scaffold/runners" / script)],
            cwd=ROOT,
            check=True,
        )
    rows = snapshot()
    write(STATUS, "COMPLETE_AND_EXPORTED", rows, source_matched=True)
    write(CANONICAL_STATUS, "COMPLETE_AND_EXPORTED_WITH_RECOVERY", rows,
          source_matched=True, recovery_reason="process.interrupted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
