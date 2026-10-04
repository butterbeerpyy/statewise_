from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from scaffold.runners import method_freeze_v1
from scaffold.statewise.experiments.experiment_manager import (
    ExperimentManager,
    RetryPolicy,
    build_episodes_from_snapshot,
    write_atomic,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = PROJECT_ROOT / "scaffold" / "experiments" / "test_set_42_v1.json"
CASES_ROOT = PROJECT_ROOT / "scaffold" / "cases"
OUTPUT_ROOT = PROJECT_ROOT / "runs" / "experiment_manager_smoke"


def _worker(spec, context):
    case_path = CASES_ROOT / spec.payload["case_file"]
    case = json.loads(case_path.read_text(encoding="utf-8"))
    heartbeat = {
        "episode_id": spec.episode_id,
        "case_id": spec.case_id,
        "attempt": context.attempt,
        "workspace": str(context.workspace),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    write_atomic(context.workspace / "worker_heartbeat.json", heartbeat)
    return {
        "case_id": case["case_id"],
        "condition": spec.condition,
        "trial": spec.trial,
        "validation": {
            "json_loaded": True,
            "case_id_matches_snapshot": case["case_id"] == spec.case_id,
            "execution_tier": case.get("execution", {}).get("tier", "symbolic"),
            "workspace_heartbeat": True,
        },
        "api_metrics": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-id",
        default=datetime.now(timezone.utc).strftime("manager-smoke-42-%Y%m%dT%H%M%SZ"),
    )
    parser.add_argument("--max-concurrency", type=int, default=4)
    args = parser.parse_args()

    freeze = method_freeze_v1.verify()
    if not freeze["valid"]:
        raise SystemExit("StateWise-v1 freeze mismatch")
    episodes = build_episodes_from_snapshot(SNAPSHOT, ["manager_validation"], 1)
    manager = ExperimentManager(
        OUTPUT_ROOT,
        args.run_id,
        {
            "kind": "experiment_manager_infrastructure_smoke",
            "live_api": False,
            "model": "deepseek-v4-flash",
            "method_freeze": freeze,
            "capability_score_eligible": False,
        },
        episodes,
        dataset_snapshot=SNAPSHOT,
        cases_root=CASES_ROOT,
        max_concurrency=args.max_concurrency,
        retry_policy=RetryPolicy(
            max_attempts=2,
            initial_backoff_seconds=0,
            max_backoff_seconds=0,
        ),
        provider_profiles=['api_01'],
        resume=True,
    )
    manifest = manager.run(_worker)
    print(json.dumps({
        "manifest": str(manager.manifest_path),
        "status": manifest["status"],
        "aggregate": manifest["aggregate"],
    }, ensure_ascii=False, indent=2))
    return 0 if manifest["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
