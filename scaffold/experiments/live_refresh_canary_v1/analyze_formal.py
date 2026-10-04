from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


ARMS = ("corrupted", "live_refresh", "statewise_v2_contract_corrected_typedfix")


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: analyze_formal.py RUN_DIR SNAPSHOT_JSON")
    run = Path(sys.argv[1])
    snapshot = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    summary = json.loads((run / "pilot_summary.json").read_text(encoding="utf-8"))
    meta = {c["case_id"]: c for c in snapshot["cases"]}
    checkpoints = {}
    for path in (run / "checkpoints").glob("*.json"):
        obj = json.loads(path.read_text(encoding="utf-8"))
        checkpoints[obj["episode_id"]] = obj
    rows = []
    errors = []
    for rec in summary["records"]:
        eid = rec["episode_id"]
        cp = checkpoints.get(eid)
        raw = None
        if cp:
            attempts = cp.get("state", {}).get("attempts", [])
            if attempts:
                raw = attempts[-1].get("result", {}).get("raw_result")
        if rec["arm"] == "live_refresh":
            if not raw:
                errors.append(f"missing raw_result: {eid}")
            else:
                lr = raw.get("live_refresh") or {}
                if lr.get("repair_performed") is not False:
                    errors.append(f"live refresh repair flag: {eid}")
                if raw.get("final_memory") != raw.get("initial_memory"):
                    errors.append(f"live refresh memory changed: {eid}")
                if lr.get("clarification_performed") is not False:
                    errors.append(f"live refresh clarification: {eid}")
        api = rec.get("api") or {}
        lr = (raw or {}).get("live_refresh") or {}
        rows.append({
            "case_id": rec["case_id"], "domain": meta.get(rec["case_id"], {}).get("domain", ""),
            "expected_behavior": meta.get(rec["case_id"], {}).get("expected_behavior", ""),
            "arm": rec["arm"], "status": rec["status"], "task_success": rec["task_success"],
            "safe_terminal": rec["acceptable_safe_terminal"], "safety_violation": rec["safety_violation"],
            "steps": rec["steps"], "replan_count": rec["replan_count"],
            "memory_changed": rec["memory_changed"], "repair_performed": rec["repair_performed"],
            "refresh_index": lr.get("refresh_index", ""),
            "refresh_read_count": len(lr.get("refresh_actions", [])),
            "api_calls": api.get("calls", 0), "api_total_tokens": api.get("total_tokens", 0),
        })
    fields = list(rows[0]) if rows else []
    with (run / "formal_case_table.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)

    by_domain = defaultdict(dict)
    domains = sorted({r["domain"] for r in rows})
    for domain in domains:
        for arm in ARMS:
            subset = [r for r in rows if r["domain"] == domain and r["arm"] == arm]
            if subset:
                by_domain[domain][arm] = {
                    "n": len(subset), "task_success": sum(bool(r["task_success"]) for r in subset),
                    "safe_terminal": sum(bool(r["safe_terminal"]) for r in subset),
                    "safety_violation": sum(bool(r["safety_violation"]) for r in subset),
                    "mean_refresh_reads": round(sum(r["refresh_read_count"] for r in subset) / len(subset), 3),
                }
    report = {
        "schema_version": "live-refresh-formal-audit-v1", "run_id": summary.get("run_id"),
        "manifest_status": summary.get("manager_status"), "pairing_valid": summary.get("pairing_valid"),
        "record_count": len(rows), "expected_record_count": len(meta) * len(ARMS),
        "final_status_counts": dict(Counter(r["status"] for r in rows)), "errors": errors,
        "live_refresh_contract_valid": not errors,
        "by_arm": {}, "by_domain": by_domain,
    }
    for arm in ARMS:
        subset = [r for r in rows if r["arm"] == arm]
        report["by_arm"][arm] = {
            "n": len(subset), "task_success": sum(bool(r["task_success"]) for r in subset),
            "safe_terminal": sum(bool(r["safe_terminal"]) for r in subset),
            "safety_violation": sum(bool(r["safety_violation"]) for r in subset),
            "mean_steps": round(sum(r["steps"] for r in subset) / len(subset), 4) if subset else None,
            "api_calls": sum(r["api_calls"] for r in subset),
            "api_total_tokens": sum(r["api_total_tokens"] for r in subset),
        }
    (run / "formal_live_refresh_audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
