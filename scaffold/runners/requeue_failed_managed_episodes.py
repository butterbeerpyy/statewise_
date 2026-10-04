from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil

from scaffold.statewise.experiments.experiment_manager import write_atomic


_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]+")


def _checkpoint_path(run_dir: Path, episode_id: str) -> Path:
    suffix = hashlib.sha256(episode_id.encode("utf-8")).hexdigest()[:24]


    return run_dir / "checkpoints" / f"cp-{suffix}.json"


def _terminal_rows(manifest):
    rows = []
    for episode_id, state in manifest.get("episodes", {}).items():
        if state.get("status") != "FAILED_TERMINAL":
            continue
        attempts = state.get("attempts") or []
        failure = attempts[-1].get("failure", {}) if attempts else {}
        rows.append({
            "episode_id": episode_id,
            "attempt_count": len(attempts),
            "failure_kind": failure.get("kind"),
            "error_type": failure.get("error_type"),
            "message": failure.get("message"),
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the correction; omission is a read-only dry run",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    if manifest_path.name != "manifest.json" or not manifest_path.is_file():
        raise SystemExit(f"invalid managed manifest: {manifest_path}")
    run_dir = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") == "RUNNING":
        raise SystemExit("refusing to requeue episodes in a RUNNING manifest")

    retry_limit = int(
        manifest.get("manager", {})
        .get("retry_policy", {})
        .get("max_attempts", 0)
    )
    rows = _terminal_rows(manifest)
    blocked = [
        row for row in rows if row["attempt_count"] >= retry_limit
    ]
    report = {
        "run_id": manifest.get("run_id"),
        "manifest_status": manifest.get("status"),
        "config_fingerprint": manifest.get("config_fingerprint"),
        "retry_limit": retry_limit,
        "terminal_count": len(rows),
        "requeueable_count": len(rows) - len(blocked),
        "blocked_by_retry_budget": blocked,
        "episodes": rows,
        "applied": False,
    }
    if not args.apply:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    if blocked:
        raise SystemExit(
            "some terminal episodes exhausted the existing retry budget; "
            "use a new correction run instead of mutating the frozen policy"
        )
    if not rows:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = run_dir / "corrections" / f"requeue-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(manifest_path, backup_dir / "manifest.before.json")

    changed = []
    changed_at = datetime.now(timezone.utc).isoformat()
    for row in rows:
        episode_id = row["episode_id"]
        checkpoint_path = _checkpoint_path(run_dir, episode_id)
        if not checkpoint_path.is_file():
            raise SystemExit(f"missing checkpoint for {episode_id}: {checkpoint_path}")
        shutil.copy2(
            checkpoint_path,
            backup_dir / (
                "checkpoint-"
                + hashlib.sha256(episode_id.encode("utf-8")).hexdigest()[:12]
                + ".before.json"
            ),
        )
        state = manifest["episodes"][episode_id]
        state.setdefault("correction_history", []).append({
            "changed_at": changed_at,
            "from_status": "FAILED_TERMINAL",
            "to_status": "PENDING",
            "preserved_attempt_count": len(state.get("attempts") or []),
            "failure_kind": row["failure_kind"],
            "reason": "user_authorized_checkpoint_completion",
        })
        state["status"] = "PENDING"
        write_atomic(checkpoint_path, {
            "schema_version": manifest.get("schema_version"),
            "run_id": manifest.get("run_id"),
            "episode_id": episode_id,
            "updated_at": changed_at,
            "state": state,
        })
        changed.append(episode_id)

    manifest.setdefault("correction_history", []).append({
        "changed_at": changed_at,
        "backup_dir": str(backup_dir),
        "requeued_episode_ids": changed,
        "reason": "user_authorized_checkpoint_completion",
    })
    manifest["status"] = "CORRECTION_PENDING"
    manifest["updated_at"] = changed_at
    write_atomic(manifest_path, manifest)
    report.update({
        "applied": True,
        "backup_dir": str(backup_dir),
        "requeued_episode_ids": changed,
    })
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
