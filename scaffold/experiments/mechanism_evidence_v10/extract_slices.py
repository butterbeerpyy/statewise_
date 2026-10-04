from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build import OUTPUT_ROOT, RQ4_RUN, read_json, write_json
from validate import validate_plan, validate_rq4


def successful_result(episode: dict[str, Any]) -> dict[str, Any] | None:
    if episode.get("status") != "SUCCEEDED":
        return None
    for attempt in reversed(episode.get("attempts") or []):
        if attempt.get("status") == "SUCCEEDED" and attempt.get("result"):
            return attempt["result"]
    return None


def extract(plan: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    registry = manifest["experiment_config"]["arm_registry"]
    rows = []
    for case in plan["cases"]:
        for arm in plan["arms"]:
            episode_id = f"{case['case_id']}--{arm}--trial-000"
            episode = manifest["episodes"][episode_id]
            result = successful_result(episode)
            rows.append(
                {
                    **case,
                    "episode_id": episode_id,
                    "arm": arm,
                    "trial": 0,
                    "status": episode.get("status"),
                    "arm_fingerprint": registry[arm]["implementation"]["fingerprint"],
                    "attempt_count": len(episode.get("attempts") or []),
                    "summary": (result or {}).get("summary"),
                    "shared_setup": (result or {}).get("shared_setup"),
                    "worker_isolation": (result or {}).get("worker_isolation"),
                }
            )
    return {
        "schema_version": "statewise-mechanism-slice-results-v1",
        "slice_id": plan["slice_id"],
        "source_run_id": manifest["run_id"],
        "source_config_fingerprint": manifest["config_fingerprint"],
        "selection_fingerprint": plan["selection_fingerprint"],
        "complete": all(row["status"] == "SUCCEEDED" for row in rows),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--rq4-manifest", type=Path, default=RQ4_RUN / "manifest.json")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parent / "extracted",
    )
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    frozen_root = args.frozen_root.resolve()
    errors: list[str] = []
    plans = [
        validate_plan(frozen_root, "replanning", 25, errors),
        validate_plan(frozen_root, "residual_gate", 20, errors),
    ]
    rq4_summary = validate_rq4(args.rq4_manifest.resolve(), plans, errors)
    manifest = read_json(args.rq4_manifest.resolve())
    if manifest.get("status") != "COMPLETE" and not args.allow_incomplete:
        errors.append(f"RQ4 run is {manifest.get('status')}; extraction requires COMPLETE")
    slices = [extract(plan, manifest) for plan in plans]
    if not args.allow_incomplete:
        for item in slices:
            if not item["complete"]:
                errors.append(f"slice is incomplete: {item['slice_id']}")
    if not args.check_only and not errors:
        for item in slices:
            write_json(args.output_root.resolve() / f"{item['slice_id']}.json", item)
    print(
        json.dumps(
            {
                "valid": not errors,
                "errors": errors,
                "rq4": rq4_summary,
                "slices": [
                    {
                        "slice_id": item["slice_id"],
                        "cells": len(item["rows"]),
                        "complete": item["complete"],
                    }
                    for item in slices
                ],
                "wrote_files": not args.check_only and not errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
