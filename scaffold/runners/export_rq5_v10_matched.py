from __future__ import annotations
import argparse, json
from collections import defaultdict
from pathlib import Path
import hashlib
import shutil
from statistics import mean
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = Path('runs/')
CONTROL_ARMS = {"cor":"corrupted", "nom":"no_memory", "crt":"correct", "fin":"statewise_v2_contract_corrected_typedfix", "orc":"oracle_statewise"}
BASELINE_ARMS = {"mem":"memlineage_trust", "saf":"safety_sentry", "ask":"ask_or_assume"}
ARMS = {**CONTROL_ARMS, **BASELINE_ARMS}
PAPER_ARMS = {
    "statewise_v2_contract_corrected_typedfix",
    "memlineage_trust",
    "safety_sentry",
    "ask_or_assume",
}
DIAGNOSTIC_ARMS = {"corrupted", "no_memory", "correct", "oracle_statewise"}
DOMAINS = {"env":"environment", "git":"git", "db":"database", "dep":"deployment"}
SAFETY_RECOVERY_SEQUENCES = {
    "env": ["seq_environment_008"],
    "git": ["seq_git_007", "seq_git_008"],
    "db": ["seq_database_008"],
}
OUT = ROOT / 'paper_experiments/results/rq5/rq5_v10_matched.xlsx'
PUBLIC_OUT = ROOT / 'paper_experiments/results/rq5/rq5_results.xlsx'
EXPECTED_CODE_HASHES = {
    "scaffold/runners/run_rq5_longitudinal_real.py": "43d82c8b558d521ce04386c1b1991a173ecc511d941cd087387e1044d369ff7a",
    "scaffold/statewise/evaluation/longitudinal_runtime.py": "22155e13e81af07f558e0901d051f76aed745fe92c4520a4d667e39747e1d811",
    "scaffold/statewise/evaluation/longitudinal_schema.py": "efc90579f490e901ccef46a2c0fb1228f19a67379c6c7350f7dacae2fdd72317",
    "scaffold/statewise/experiments/pilot_conditions.py": "ba12ee8679e7f507e3a117b7f8ff6351bd43e16f9945969542e8e1a79955750a",
    "scaffold/statewise/runtime/lightweight_runtime.py": "844f36ee193f05cb1c12b46a34de55855a58f6b053b9a1171d601d1c314ae4ec",
    "scaffold/statewise/runtime/structured_mutation_runtime.py": "00b14b89334287ee06c704a79e848aac94780213a91f1528b88e07b17f099540",
}
PAPER_LABELS = {
    "statewise_v2_contract_corrected_typedfix": "StateWise",
    "memlineage_trust": "MemLineage",
    "safety_sentry": "Safety Sentry",
    "ask_or_assume": "Ask-or-Assume",
}

def canonical_fingerprint(value):
    payload=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return "sha256:"+hashlib.sha256(payload.encode("utf-8")).hexdigest()

def all_episodes_terminal(manifest):
    episodes = manifest.get("episodes") or {}
    return bool(episodes) and all(
        episode.get("status") in {"SUCCEEDED", "FAILED_TERMINAL"}
        for episode in episodes.values()
    )

def validate_run(
    path,
    manifest,
    expected_sequences,
    allowed_statuses={"COMPLETE"},
    *,
    allow_stale_running_terminal=False,
):
    stale_running_terminal = (
        allow_stale_running_terminal
        and manifest.get("status") == "RUNNING"
        and all_episodes_terminal(manifest)
    )
    if manifest.get("status") not in allowed_statuses and not stale_running_terminal:
        raise ValueError(f"invalid status at {path}: {manifest.get('status')}")
    cfg = manifest["experiment_config"]
    if cfg.get("model") != "gpt-5.6-sol" or cfg.get("fake_api"): raise ValueError(f"wrong config: {path}")
    if cfg.get("sequences") != expected_sequences:
        raise ValueError(f"wrong sequence scope: {path}")
    if cfg.get("dataset", {}).get("composite_sha256") != "a871a91427dd4a5bead0115be695bb74df28a660b25990103cdece681b4b7a62":
        raise ValueError(f"wrong dataset fingerprint: {path}")
    if cfg.get("measurement_code_fingerprints") != EXPECTED_CODE_HASHES:
        raise ValueError(f"measurement code does not match StateWise runs: {path}")

def load_runs(domain, arm):
    suffix = "b3" if arm in BASELINE_ARMS else "1"
    path = RUN_ROOT / f"r5v10-{domain}-{arm}-{suffix}"
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    expected_domain = DOMAINS[domain]
    expected_sequences = [f"seq_{expected_domain}_{index:03d}" for index in range(1, 9)]
    recovery_sequences = SAFETY_RECOVERY_SEQUENCES.get(domain, []) if arm == "saf" else []
    if not recovery_sequences:
        validate_run(path, manifest, expected_sequences)
        return [(path, manifest)]


    validate_run(
        path,
        manifest,
        expected_sequences,
        {"COMPLETE_WITH_FAILURES"},
        allow_stale_running_terminal=True,
    )
    failed = []
    for episode_id, episode in manifest.get("episodes", {}).items():
        if episode.get("status") != "FAILED_TERMINAL":
            continue
        failures = [attempt.get("failure") or {} for attempt in episode.get("attempts", [])]
        if not failures or any(item.get("kind") != "process.interrupted" for item in failures):
            raise ValueError(f"non-infrastructure base failure: {path} {episode_id}")
        failed.append(episode_id.split("--", 1)[0])
    if sorted(failed) != sorted(recovery_sequences):
        raise ValueError(f"recovery scope does not match base failures: {path}")

    recovery_path = RUN_ROOT / f"r5v10-{domain}-saf-b3-recovery1"
    recovery = json.loads((recovery_path / "manifest.json").read_text(encoding="utf-8"))
    validate_run(recovery_path, recovery, recovery_sequences)
    return [(path, manifest), (recovery_path, recovery)]

def successful_sequence_rows(path, manifest):
    rows = []
    for episode in manifest.get("episodes", {}).values():
        if episode.get("status") != "SUCCEEDED":
            continue
        result = episode["attempts"][-1].get("result") or {}
        metrics = result.get("metrics")
        if not metrics:
            raise ValueError(f"successful episode lacks metrics: {path}")
        rows.append({
            "sequence_id": result.get("sequence_id"),
            "trial": episode["spec"]["trial"],
            **metrics,
        })
    rows.sort(key=lambda row: (row["sequence_id"], row["trial"], row["arm"]))


    summary_path = path / "longitudinal_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary_rows = sorted(
            summary.get("sequence_arm_results", []),
            key=lambda row: (row["sequence_id"], row["trial"], row["arm"]),
        )
        if summary_rows != rows:
            raise ValueError(f"summary/manifest sequence mismatch: {path}")
    return rows

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output",type=Path,default=OUT); args=ap.parse_args()
    seq_rows=[]; task_rows=[]; prov=[]
    for dcode, domain in DOMAINS.items():
      for acode, arm in ARMS.items():
        for path,m in load_runs(dcode,acode):
          cfg=m["experiment_config"]
          implementation=(((cfg.get("arm_registry") or {}).get(arm) or {}).get("implementation") or {})
          stale_terminal = m["status"] == "RUNNING" and all_episodes_terminal(m)
          effective_status = "COMPLETE_WITH_FAILURES" if stale_terminal else m["status"]
          recovery_role = (
              "replacement" if path.name.endswith("-recovery1") else
              "superseded_interrupted_base" if arm == "safety_sentry" and any(
                  episode.get("status") == "FAILED_TERMINAL"
                  for episode in m.get("episodes", {}).values()
              ) else "primary"
          )
          prov.append({"run_id":m["run_id"],"domain":domain,"arm":arm,"status":effective_status,"source_manifest_status":m["status"],"recovery_role":recovery_role,"model":cfg["model"],"api_profile":cfg["api_profile"],"method_fingerprint":(cfg.get("final_v2") or {}).get("fingerprint"),"arm_implementation_fingerprint":canonical_fingerprint(implementation),"measurement_code_fingerprint":canonical_fingerprint(cfg["measurement_code_fingerprints"]),"dataset_sha256":cfg["dataset"]["composite_sha256"],"sequences":len(cfg["sequences"]),"calls":m["aggregate"]["usage"]["calls"],"prompt_tokens":m["aggregate"]["usage"]["prompt_tokens"],"completion_tokens":m["aggregate"]["usage"]["completion_tokens"],"total_tokens":m["aggregate"]["usage"]["total_tokens"],"latency_seconds":m["aggregate"]["usage"]["latency_seconds"],"manifest":str(path/'manifest.json')})
          for item in successful_sequence_rows(path, m):
            row=dict(item); row.update({"domain":domain,"arm":arm,"run_id":m["run_id"],"primary_in_scope":True}); seq_rows.append(row)
            eid=f"{item['sequence_id']}--{arm}--trial-{item['trial']:03d}"; result=m["episodes"][eid]["attempts"][-1]["result"]
            for t in result["tasks"]:
              s=t["summary"]; task_rows.append({"run_id":m["run_id"],"domain":domain,"arm":arm,"sequence_id":item["sequence_id"],"task_id":t["task_id"],"task_index":t["task_index"],"task_success":s["task_success"],"risk_adjusted_task_success":s["risk_adjusted_task_success"],"safety_violation":s["safety_violation"],"status":s.get("status"),"repair_performed":s.get("repair_performed"),"repair_correct":s.get("repair_correct"),"terminal_reason":s.get("terminal_reason") or s.get("status"),"handoff":t["inherited_previous_final_exactly"],"state_reuse":t["repaired_memory_entered_planner_context"],"contract_after":t["memory_contract_after"]["repaired_contract_satisfied"]})
    wb=Workbook(); wb.remove(wb.active)
    def sheet(name, rows):
      ws=wb.create_sheet(name); headers=list(rows[0]) if rows else []; ws.append(headers)
      for r in rows: ws.append([r.get(h) for h in headers])
    grouped=defaultdict(list)
    for r in seq_rows: grouped[r["arm"]].append(r)
    provenance_by_arm=defaultdict(list)
    for r in prov: provenance_by_arm[r["arm"]].append(r)
    summaries=[]
    for arm, rows in grouped.items():
      n=len(rows); tasks=sum(r["tasks"] for r in rows); future=3*n
      usage=provenance_by_arm[arm]
      calls=sum(r["calls"] for r in usage); tokens=sum(r["total_tokens"] for r in usage); latency=sum(r["latency_seconds"] for r in usage)
      future_task_rows = [
          item for item in task_rows
          if item["arm"] == arm and int(item["task_index"]) > 1
      ]
      summaries.append({"arm":arm,"sequences":n,"tasks":tasks,"task_success_rate":sum(r["task_success_count"] for r in rows)/tasks,"future_task_success_rate":sum(r["future_task_success_count"] for r in rows)/future,"t1_repair_success_rate":sum(bool(r["t1_repaired_contract_satisfied"]) for r in rows)/n,"future_no_violation_rate":mean(r.get("future_no_violation_rate", r.get("future_task_safety_rate")) for r in rows),"future_safe_completion_rate":sum(bool(item["risk_adjusted_task_success"]) for item in future_task_rows)/len(future_task_rows),"state_handoff_integrity_rate":mean(r["state_handoff_integrity_rate"] for r in rows),"state_reuse_rate":mean(r["state_reuse_rate"] for r in rows),"repeated_intervention_rate":mean(r["repeated_intervention_rate"] for r in rows),"safety_violations":sum(r["cumulative_safety_violations"] for r in rows),"api_calls_per_task":calls/tasks,"tokens_per_task":tokens/tasks,"api_latency_seconds_per_task":latency/tasks})
    paper = [
        {"method": PAPER_LABELS[row["arm"]], **{key:value for key,value in row.items() if key != "arm"}}
        for row in summaries if row["arm"] in PAPER_ARMS
    ]
    diagnostic = [row for row in summaries if row["arm"] in DIAGNOSTIC_ARMS]
    domain_summary=[]
    for (domain, arm), rows in sorted(
        ((key, [row for row in seq_rows if (row["domain"], row["arm"]) == key])
         for key in {(row["domain"], row["arm"]) for row in seq_rows}),
        key=lambda item: item[0],
    ):
      tasks=sum(row["tasks"] for row in rows); future=3*len(rows)
      domain_summary.append({"domain":domain,"arm":arm,"sequences":len(rows),"task_success_rate":sum(row["task_success_count"] for row in rows)/tasks,"future_task_success_rate":sum(row["future_task_success_count"] for row in rows)/future,"future_no_violation_rate":mean(row.get("future_no_violation_rate",row.get("future_task_safety_rate")) for row in rows),"safety_violations":sum(row["cumulative_safety_violations"] for row in rows)})
    sheet("Paper_Comparison",paper)
    sheet("Diagnostic_Controls",diagnostic)
    sheet("All_Summary",summaries)
    sheet("Domain_Summary",domain_summary)
    sheet("Sequence_Data",seq_rows); sheet("Task_Data",task_rows); sheet("Run_Provenance",prov)
    failures=[]
    for r in task_rows:
      if not r["task_success"]: failures.append({"domain":r["domain"],"arm":r["arm"],"sequence_id":r["sequence_id"],"task_id":r["task_id"],"safety_violation":r["safety_violation"],"terminal_reason":r["terminal_reason"]})
    sheet("Failures",failures or [{"status":"none"}]); args.output.parent.mkdir(parents=True,exist_ok=True); wb.save(args.output)
    if args.output.resolve() == OUT.resolve():
        shutil.copyfile(args.output, PUBLIC_OUT)
    print(args.output.resolve())
if __name__ == "__main__": main()
