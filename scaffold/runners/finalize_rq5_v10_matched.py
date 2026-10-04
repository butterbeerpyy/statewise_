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
STATUS = RESULT_ROOT / "RQ5_V10_MATCHED_STATUS.json"
RUN_IDS = tuple(
    f"r5v10-{domain}-{arm}-b3"
    for domain in ("env", "git", "db", "dep")
    for arm in ("mem", "saf", "ask")
)
TERMINAL_BAD = {"FAILED", "COMPLETE_WITH_FAILURES"}


def load_manifest(run_id: str) -> dict | None:
    try:
        return json.loads(
            (RUN_ROOT / run_id / "manifest.json").read_text(encoding="utf-8")
        )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def active_run_ids() -> set[str]:
    active = set()
    for process in psutil.process_iter(("cmdline",)):
        try:
            command = " ".join(process.info.get("cmdline") or [])
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        for run_id in RUN_IDS:
            if run_id in command:
                active.add(run_id)
    return active


def age_minutes(manifest: dict) -> float:
    updated = datetime.fromisoformat(manifest["updated_at"].replace("Z", "+00:00"))
    return max(0.0, (datetime.now(timezone.utc) - updated).total_seconds() / 60)


def resume(run_id: str) -> int:
    run_dir = RUN_ROOT / run_id
    stdout = (run_dir / "matched-supervisor.stdout.log").open("ab")
    stderr = (run_dir / "matched-supervisor.stderr.log").open("ab")
    environment = os.environ.copy()
    environment["STATEWISE_RESUME_ROOT"] = str(METHOD_ROOT)
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scaffold/runners/resume_rq5_supervised.py"),
            "--manifest", str(run_dir / "manifest.json"),
            "--stale-minutes", "30",
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


def snapshot() -> list[dict]:
    active = active_run_ids()
    rows = []
    for run_id in RUN_IDS:
        manifest = load_manifest(run_id)
        counts = (manifest or {}).get("aggregate", {}).get("status_counts", {})
        rows.append({
            "run_id": run_id,
            "status": (manifest or {}).get("status", "NO_MANIFEST"),
            "succeeded": int(counts.get("SUCCEEDED", 0)),
            "failed": int(counts.get("FAILED_TERMINAL", 0)),
            "age_minutes": round(age_minutes(manifest), 2) if manifest else None,
            "active": run_id in active,
        })
    return rows


def write_status(status: str, rows: list[dict], **extra) -> None:
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps({
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "runs": rows,
        **extra,
    }, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    while True:
        rows = snapshot()
        if any(row["status"] in TERMINAL_BAD or row["failed"] for row in rows):
            write_status("BLOCKED_BY_TERMINAL_FAILURE", rows)
            return 2
        if all(row["status"] == "COMPLETE" and row["succeeded"] == 8 for row in rows):
            break
        resumed = []
        for row in rows:
            if (
                row["status"] not in {"COMPLETE", "NO_MANIFEST"}
                and not row["active"]
                and row["age_minutes"] is not None
                and row["age_minutes"] >= 30
            ):
                resumed.append({"run_id": row["run_id"], "pid": resume(row["run_id"])})
        write_status("RUNNING", rows, resumed=resumed)
        time.sleep(60)

    subprocess.run(
        [sys.executable, str(ROOT / "scaffold/runners/export_rq5_v10_matched.py")],
        cwd=ROOT, check=True,
    )
    subprocess.run(
        [sys.executable, str(ROOT / "scaffold/runners/analyze_rq5_v10_paired.py")],
        cwd=ROOT, check=True,
    )
    subprocess.run(
        [sys.executable, str(ROOT / "scaffold/runners/validate_rq5_v10_matched.py")],
        cwd=ROOT, check=True,
    )
    write_status("COMPLETE_AND_EXPORTED", snapshot(), source_matched=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
