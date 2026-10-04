from __future__ import annotations
import argparse, hashlib, json
from collections import Counter
from pathlib import Path

REQUIRED = (
    "case_id", "domain", "task", "corruption_operator", "corrupted_state",
    "correct_state", "ground_truth_state", "oracle_support_states", "safety",
    "execution", "expected",
)

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def _second_annotation_status(report_path: Path) -> dict:

    if not report_path.exists():
        return {"independent_second_annotation": "NOT_PRESENT",
                "agreement": "NOT_COMPUTABLE"}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "COMPLETE" or not report.get("agreement"):
        return {
            "independent_second_annotation": "INCOMPLETE",
            "agreement": "NOT_COMPUTABLE",
            "independent_annotation_completed_items": report.get("completed_items"),
            "independent_annotation_incomplete_items": report.get("incomplete_items"),
        }
    return {
        "independent_second_annotation": "PRESENT",
        "independent_annotation_items": report.get("items"),
        "agreement": report["agreement"],
        "agreement_report": str(report_path),
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--snapshot",type=Path,default=Path('scaffold\\experiments\\w1_contract_corrected_v9\\snapshot.json'))
    p.add_argument("--output",type=Path,default=Path('paper_experiments/results/shared/audit/FINAL_150_V9_ANNOTATION_AUDIT.json'))
    p.add_argument("--agreement-report",type=Path,default=Path('paper_experiments/results/shared/annotation_b_v9/agreement_report.json'))
    a=p.parse_args(); snap=json.loads(a.snapshot.read_text(encoding="utf-8")); root=a.snapshot.parent/"cases"
    rows=[]
    for entry in snap["cases"]:
        path=root/entry["file"]; case=json.loads(path.read_text(encoding="utf-8")); oracle=(case.get("execution") or {}).get("oracle") or {}
        missing=[k for k in REQUIRED if case.get(k) in (None, "", []) and k != "oracle_support_states"]
        support=case.get("oracle_support_states")
        rows.append({
            "case_id":case.get("case_id"),"domain":case.get("domain"),"operator":case.get("corruption_operator"),
            "sha_matches_snapshot":sha(path)==entry["sha256"],"missing_required":missing,
            "support_annotation_present":isinstance(support,list) and bool(support),
            "safety_invariant_present":bool((case.get("safety") or {}).get("invariant")),
            "fixture_present":isinstance((case.get("execution") or {}).get("fixture"),dict),
            "oracle_present":isinstance(oracle,dict) and bool(oracle),
            "completion_or_safe_stop_present":bool(oracle.get("completion_actions") or oracle.get("safe_terminal_actions") or oracle.get("safe_terminal_outcome")),
        })
    report={
        "snapshot_id":snap.get("snapshot_id"),"snapshot_sha256":sha(a.snapshot),"case_count":len(rows),
        "all_case_hashes_match":all(r["sha_matches_snapshot"] for r in rows),
        "complete_required_fields":sum(not r["missing_required"] for r in rows),
        "support_annotation_present":sum(r["support_annotation_present"] for r in rows),
        "safety_invariant_present":sum(r["safety_invariant_present"] for r in rows),
        "fixture_present":sum(r["fixture_present"] for r in rows),"oracle_present":sum(r["oracle_present"] for r in rows),
        "completion_or_safe_stop_present":sum(r["completion_or_safe_stop_present"] for r in rows),
        "domains":dict(Counter(r["domain"] for r in rows)),"operators":dict(Counter(r["operator"] for r in rows)),
        **_second_annotation_status(a.agreement_report),
        "rows":rows,
    }
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps({k:v for k,v in report.items() if k!="rows"},ensure_ascii=False,indent=2))
if __name__=="__main__": main()
