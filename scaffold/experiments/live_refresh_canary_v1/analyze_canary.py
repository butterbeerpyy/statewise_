from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: analyze_canary.py RUN_DIR SNAPSHOT_JSON")
    run_dir = Path(sys.argv[1])
    snapshot = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "pilot_summary.json").read_text(encoding="utf-8"))
    meta = {c["case_id"]: c for c in snapshot["cases"]}
    rows = []
    for rec in sorted(summary["records"], key=lambda r: (r["case_id"], r["arm"])):
        api = rec.get("api") or {}
        rows.append({
            "case_id": rec["case_id"],
            "domain": meta.get(rec["case_id"], {}).get("domain", ""),
            "expected_behavior": meta.get(rec["case_id"], {}).get("expected_behavior", ""),
            "arm": rec["arm"],
            "status": rec["status"],
            "task_success": rec["task_success"],
            "safe_terminal": rec["acceptable_safe_terminal"],
            "safety_violation": rec["safety_violation"],
            "steps": rec["steps"],
            "replan_count": rec["replan_count"],
            "memory_changed": rec["memory_changed"],
            "repair_performed": rec["repair_performed"],
            "repair_correct": rec["repair_correct"],
            "final_tool": (rec.get("final_action") or {}).get("tool", ""),
            "final_operation": (rec.get("final_action") or {}).get("operation", ""),
            "api_calls": api.get("calls", 0),
            "api_total_tokens": api.get("total_tokens", 0),
        })
    out_csv = run_dir / "canary_case_table.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    live = [r for r in rows if r["arm"] == "live_refresh"]
    audit = {
        "run_id": summary["run_id"],
        "pairing_valid": summary.get("pairing_valid"),
        "record_count": len(rows),
        "live_refresh_records": len(live),
        "live_refresh_contract": {
            "all_memory_unchanged": all(not r["memory_changed"] for r in live),
            "all_repairs_false": all(not r["repair_performed"] for r in live),
            "safety_violations": sum(bool(r["safety_violation"]) for r in live),
            "task_successes": sum(bool(r["task_success"]) for r in live),
            "safe_terminals": sum(bool(r["safe_terminal"]) for r in live),
        },
        "by_domain": {},
    }
    for domain in sorted({r["domain"] for r in rows}):
        audit["by_domain"][domain] = {}
        for arm in sorted({r["arm"] for r in rows}):
            subset = [r for r in rows if r["domain"] == domain and r["arm"] == arm]
            if subset:
                audit["by_domain"][domain][arm] = {
                    "n": len(subset),
                    "task_success": sum(bool(r["task_success"]) for r in subset),
                    "safe_terminal": sum(bool(r["safe_terminal"]) for r in subset),
                    "safety_violation": sum(bool(r["safety_violation"]) for r in subset),
                }
    (run_dir / "canary_contract_audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(audit, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
