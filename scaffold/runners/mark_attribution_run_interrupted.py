from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from scaffold.runners.run_episode_real import _write_atomic


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--pid", type=int)
    args = parser.parse_args()
    path = Path(args.manifest).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "RUNNING":
        raise SystemExit(
            f"refusing to overwrite terminal status {payload.get('status')}"
        )
    now = datetime.now(timezone.utc).isoformat()
    payload["status"] = "INTERRUPTED"
    payload["updated_at"] = now
    payload["interrupted_at"] = now
    payload["interruption"] = {
        "reason": args.reason,
        "pid": args.pid,
        "successful_records_preserved": sum(
            item.get("status") == "SUCCEEDED"
            for item in payload.get("records", [])
        ),
        "failed_records_preserved": sum(
            item.get("status") == "FAILED"
            for item in payload.get("records", [])
        ),
    }
    _write_atomic(path, payload)
    print(json.dumps({
        "manifest": str(path),
        "status": payload["status"],
        **payload["interruption"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
