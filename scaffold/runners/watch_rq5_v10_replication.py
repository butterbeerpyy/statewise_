from __future__ import annotations

import json
import os
import subprocess
import time
import ctypes
from datetime import datetime, timezone
from pathlib import Path

from launch_rq5_v10_replication import METHOD_ROOT, OUTPUT, STATUS, command


TERMINAL = {"COMPLETE", "COMPLETE_WITH_FAILURES"}
POLL_SECONDS = 60
STALE_SECONDS = 30 * 60


def now() -> datetime:
    return datetime.now(timezone.utc)


def process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":


        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ProcessLookupError, ValueError):
        return False


def read_manifest(run_id: str) -> dict:
    path = OUTPUT / run_id / "manifest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def write_status(payload: dict) -> None:
    temp = STATUS.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(STATUS)


def relaunch(item: dict) -> int:
    run_id = item["run_id"]
    stdout = (OUTPUT / f"{run_id}.stdout.log").open("a", encoding="utf-8")
    stderr = (OUTPUT / f"{run_id}.stderr.log").open("a", encoding="utf-8")
    process = subprocess.Popen(
        command(run_id, item["arm"], item["sequence_ids"]),
        cwd=METHOD_ROOT,
        stdout=stdout,
        stderr=stderr,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    stdout.close()
    stderr.close()
    return process.pid


def main() -> int:
    payload = json.loads(STATUS.read_text(encoding="utf-8"))
    while True:
        terminal_count = 0
        for item in payload["runs"]:
            manifest = read_manifest(item["run_id"])
            status = manifest.get("status", "NOT_WRITTEN")
            counts = ((manifest.get("aggregate") or {}).get("status_counts") or {})
            alive = process_alive(item.get("pid"))
            updated = parse_time(manifest.get("updated_at"))
            age = (now() - updated).total_seconds() if updated else None
            item.update({
                "manifest_status": status,
                "status_counts": counts,
                "process_alive": alive,
                "checkpoint_age_seconds": round(age, 1) if age is not None else None,
                "stale_observation": bool(age is not None and age >= STALE_SECONDS),
                "observed_at": now().isoformat(),
            })
            if status in TERMINAL:
                terminal_count += 1
                continue


            if not alive:
                item["pid"] = relaunch(item)
                item["restart_count"] = int(item.get("restart_count") or 0) + 1
                item["last_restart_at"] = now().isoformat()
        payload["terminal_runs"] = terminal_count
        payload["total_runs"] = len(payload["runs"])
        payload["updated_at"] = now().isoformat()
        if terminal_count == len(payload["runs"]):
            statuses = {item["manifest_status"] for item in payload["runs"]}
            payload["status"] = "COMPLETE" if statuses == {"COMPLETE"} else "COMPLETE_WITH_FAILURES"
            write_status(payload)
            return 0
        payload["status"] = "RUNNING"
        write_status(payload)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
