from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

import psutil


ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = Path('runs/')
RUN_IDS = tuple(
    f"r5v10-{domain}-{arm}-b2"
    for domain in ("env", "git", "db", "dep")
    for arm in ("mem", "saf", "ask")
)
TERMINAL = {"COMPLETE", "COMPLETE_WITH_FAILURES", "FAILED"}


def load_manifest(run_id: str) -> dict | None:
    path = RUN_ROOT / run_id / "manifest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def age_minutes(manifest: dict) -> float:
    updated = datetime.fromisoformat(manifest["updated_at"].replace("Z", "+00:00"))
    return max(0.0, (datetime.now(timezone.utc) - updated).total_seconds() / 60)


def active_pids() -> dict[str, int]:
    found: dict[str, int] = {}
    for process in psutil.process_iter(("pid", "cmdline")):
        try:
            command = " ".join(process.info.get("cmdline") or [])
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        if "watch_rq5_v10_baselines.py" in command:
            continue
        for run_id in RUN_IDS:
            if run_id in command:
                found[run_id] = int(process.info["pid"])
    return found


def start_supervisor(run_id: str) -> int:
    manifest = RUN_ROOT / run_id / "manifest.json"
    stdout = (RUN_ROOT / run_id / "auto-supervisor.stdout.log").open("ab")
    stderr = (RUN_ROOT / run_id / "auto-supervisor.stderr.log").open("ab")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "scaffold.runners.resume_rq5_supervised",
            "--manifest",
            str(manifest),
            "--stale-minutes",
            "30",
            "--check-seconds",
            "60",
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    stdout.close()
    stderr.close()
    return process.pid


def snapshot() -> list[dict]:
    rows = []
    pids = active_pids()
    for run_id in RUN_IDS:
        manifest = load_manifest(run_id)
        if manifest is None:
            rows.append({"run_id": run_id, "status": "NO_MANIFEST"})
            continue
        counts = manifest.get("aggregate", {}).get("status_counts", {})
        rows.append({
            "run_id": run_id,
            "status": manifest.get("status"),
            "succeeded": int(counts.get("SUCCEEDED", 0)),
            "failed": int(counts.get("FAILED_TERMINAL", 0)),
            "age_minutes": round(age_minutes(manifest), 2),
            "pid": pids.get(run_id),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    args = parser.parse_args()
    while True:
        rows = snapshot()
        print(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "runs": rows}))
        sys.stdout.flush()
        if all(row["status"] in TERMINAL for row in rows):
            return 0
        for row in rows:
            if (
                row["status"] not in TERMINAL
                and row["status"] != "NO_MANIFEST"
                and row["age_minutes"] >= 30
                and row["pid"] is None
            ):
                row["resumed_pid"] = start_supervisor(row["run_id"])
        if args.once:
            return 0
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
