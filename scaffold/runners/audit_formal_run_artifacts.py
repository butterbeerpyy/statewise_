from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def _metrics(attempt):
    result = attempt.get("result") or {}
    metrics = result.get("api_metrics") or []
    if not metrics:
        metrics = ((attempt.get("failure") or {}).get("details") or {}).get("api_metrics") or []
    return [m for m in metrics if isinstance(m, dict)]


def _failure_class(attempt):
    failure = attempt.get("failure") or {}
    kind = str(failure.get("kind") or "")
    message = str(failure.get("message") or "")
    text = (kind + " " + message).lower()
    if "keyerror" in text or kind.startswith("runtime") or kind == "unknown":
        return "RUNTIME_DEFECT"
    if kind.startswith("api.") or any(x in text for x in (
        "badrequest", "permissiondenied", "ratelimit", "timeout",
        "connection", "internalserver", "failed api call",
    )):
        return "PROVIDER_OR_API"
    if "response_contract" in text or "json" in text:
        return "MODEL_RESPONSE_CONTRACT"
    return "UNCLASSIFIED"


def audit(run_dir: Path):
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    failures, costs = [], []
    for episode_id, state in manifest.get("episodes", {}).items():
        spec = state.get("spec") or {}
        attempts = state.get("attempts") or []
        final = attempts[-1] if attempts else {}
        all_metrics = [m for attempt in attempts for m in _metrics(attempt)]
        failed_metrics = [m for m in all_metrics if m.get("ok") is False]
        costs.append({
            "run_id": manifest.get("run_id"), "episode_id": episode_id,
            "case_id": spec.get("case_id"), "arm": spec.get("condition"),
            "episode_status": state.get("status"), "attempt_count": len(attempts),
            "api_calls": len(all_metrics),
            "failed_api_calls": len(failed_metrics),
            "transport_attempts": sum(int(m.get("transport_attempts") or 0) for m in all_metrics),
            "connection_retries": sum(int(m.get("connection_retry_count") or 0) for m in all_metrics),
            "availability_failures": sum(int(m.get("availability_failure_count") or 0) for m in all_metrics),
            "availability_wait_seconds": sum(float(m.get("availability_wait_seconds") or 0) for m in all_metrics),
            "prompt_tokens": sum(int(m.get("prompt_tokens") or 0) for m in all_metrics),
            "completion_tokens": sum(int(m.get("completion_tokens") or 0) for m in all_metrics),
            "total_tokens": sum(int(m.get("total_tokens") or 0) for m in all_metrics),
            "api_latency_seconds": sum(float(m.get("elapsed_seconds") or m.get("latency_seconds") or 0) for m in all_metrics),
            "wall_seconds": sum(float(a.get("wall_seconds") or 0) for a in attempts),
        })
        if state.get("status") != "FAILED_TERMINAL":
            continue
        failure = final.get("failure") or {}
        last_metric = failed_metrics[-1] if failed_metrics else {}
        category = _failure_class(final)
        failures.append({
            "run_id": manifest.get("run_id"), "episode_id": episode_id,
            "case_id": spec.get("case_id"), "arm": spec.get("condition"),
            "attempt_count": len(attempts), "failure_category": category,
            "failure_kind": failure.get("kind"), "error_type": failure.get("error_type"),
            "message": failure.get("message"), "failed_stage": last_metric.get("stage"),
            "api_error_type": last_metric.get("error_type"),
            "recovery_action": "RERUN_EPISODE" if category != "RUNTIME_DEFECT" else "FIX_AND_RERUN_EPISODE",
        })
    return manifest, failures, costs


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["no_rows"])
        writer.writeheader()
        writer.writerows(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", action="append", required=True, type=Path)
    p.add_argument("--output-dir", type=Path, default=Path('paper_experiments/results/shared/audit/formal_v9'))
    args = p.parse_args()
    failures, costs, runs = [], [], []
    for run_dir in args.run:
        manifest, run_failures, run_costs = audit(run_dir)
        failures.extend(run_failures); costs.extend(run_costs)
        runs.append({
            "run_id": manifest.get("run_id"), "status": manifest.get("status"),
            "updated_at": manifest.get("updated_at"),
            "status_counts": dict(Counter(e.get("status") for e in manifest.get("episodes", {}).values())),
            "failure_classes": dict(Counter(x["failure_category"] for x in run_failures)),
        })
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(args.output_dir / "failure_inventory.csv", failures)
    _write_csv(args.output_dir / "episode_costs.csv", costs)
    (args.output_dir / "audit_summary.json").write_text(
        json.dumps({"runs": runs, "failure_count": len(failures)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"runs": runs, "failure_count": len(failures)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
