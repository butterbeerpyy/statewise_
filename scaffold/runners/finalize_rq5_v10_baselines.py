from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = Path('runs/')
RESULT_ROOT = ROOT / 'paper_experiments/results/rq5'
RUN_IDS = tuple(
    f"r5v10-{domain}-{arm}-b2"
    for domain in ("env", "git", "db", "dep")
    for arm in ("mem", "saf", "ask")
)


def manifest(run_id: str) -> dict | None:
    try:
        return json.loads(
            (RUN_ROOT / run_id / "manifest.json").read_text(encoding="utf-8")
        )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def write_status(status: str, rows: list[dict]) -> None:
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    (RESULT_ROOT / "RQ5_V10_BASELINE_STATUS.json").write_text(
        json.dumps({
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "runs": rows,
        }, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    while True:
        rows = []
        for run_id in RUN_IDS:
            value = manifest(run_id)
            counts = (value or {}).get("aggregate", {}).get("status_counts", {})
            rows.append({
                "run_id": run_id,
                "status": (value or {}).get("status", "NO_MANIFEST"),
                "succeeded": int(counts.get("SUCCEEDED", 0)),
                "failed": int(counts.get("FAILED_TERMINAL", 0)),
            })
        bad = [row for row in rows if row["status"] in {"FAILED", "COMPLETE_WITH_FAILURES"}]
        if bad:
            write_status("BLOCKED_BY_TERMINAL_FAILURE", rows)
            return 2
        if all(row["status"] == "COMPLETE" and row["succeeded"] == 8 for row in rows):
            break
        write_status("RUNNING", rows)
        time.sleep(60)

    subprocess.run(
        [sys.executable, str(ROOT / "scaffold/runners/export_rq5_v10_matched.py")],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [sys.executable, str(ROOT / "scaffold/runners/analyze_rq5_v10_paired.py")],
        cwd=ROOT,
        check=True,
    )
    write_status("COMPLETE_AND_EXPORTED", rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
