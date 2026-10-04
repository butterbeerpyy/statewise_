import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs" / "rq5_longitudinal"
OUT = ROOT / "runs" / "rq5_primary_scope.json"

PRIMARY_DOMAINS = ("database", "deployment", "environment", "git")
EXCLUDED_DOMAIN = "filesystem"
SEQUENCES_PER_DOMAIN = 8

BASELINE_ARMS = (
    "correct", "corrupted", "no_memory", "auto_execute", "bare_approval",
    "rationale_approval", "generic_clarification", "safety_sentry",
    "memlineage_trust", "oracle_statewise",
)
MATRIX_SHARDS = [(f"rq5v2_base_{arm}_gpt56sol", "gpt-5.6-sol") for arm in BASELINE_ARMS]
MATRIX_SHARDS += [
    ("rq5v2_method_deepseek", "deepseek-v4-pro"),
    ("rq5v2_method_qwen", "qwen3.7-max"),
]

POOLED_METHOD = (
    ["rq5_v2_full40_gpt56sol", "rq5_v2_full40_gpt56sol_part2"],
    "statewise_v2_retrieval",
    "gpt-5.6-sol",
)


def domain_of(sequence_id):
    parts = sequence_id.split("_")
    return parts[1] if len(parts) > 1 else "unknown"


def aggregate(records, scope_domains):

    in_scope = [r for r in records if domain_of(r.get("sequence_id", "")) in scope_domains]
    if not in_scope:
        return {}

    def mean(key, transform=lambda x: x):
        values = [transform(r.get(key)) for r in in_scope if r.get(key) is not None]
        return round(sum(values) / len(values), 4) if values else None

    safety_viol = sum(int(r.get("cumulative_safety_violations") or 0) for r in in_scope)
    return {
        "sequences": len(in_scope),
        "task_success_rate": mean("task_success_rate"),
        "future_task_success_rate": mean("future_task_success_rate"),
        "future_task_safety_rate": mean("future_task_safety_rate"),
        "state_handoff_integrity_rate": mean("state_handoff_integrity_rate"),
        "state_reuse_rate": mean("state_reuse_rate"),
        "t1_repaired_contract_satisfied": mean("t1_repaired_contract_satisfied", bool),
        "cumulative_safety_violations": safety_viol,
    }


cells = []
attrition = []
for run_id, model_or_arm in MATRIX_SHARDS:
    path = RUNS / run_id / "longitudinal_summary.json"
    if not path.exists():
        attrition.append(f"{run_id} (no summary)")
        continue
    summary = json.loads(path.read_text(encoding="utf-8"))
    records = summary.get("sequence_arm_results") or []
    arm = summary["table"][0]["arm"] if summary.get("table") else model_or_arm
    cells.append({
        "run_id": run_id,
        "arm": arm,
        "model": model_or_arm if arm == "statewise_v2_retrieval" else "gpt-5.6-sol",
        "primary_scope": aggregate(records, PRIMARY_DOMAINS),
        "filesystem_only": aggregate(records, (EXCLUDED_DOMAIN,)),
    })


pooled_records = []
for run_id in POOLED_METHOD[0]:
    path = RUNS / run_id / "longitudinal_summary.json"
    if path.exists():
        summary = json.loads(path.read_text(encoding="utf-8"))
        pooled_records.extend(summary.get("sequence_arm_results") or [])
if pooled_records:
    cells.append({
        "run_id": "+".join(POOLED_METHOD[0]),
        "arm": POOLED_METHOD[1],
        "model": POOLED_METHOD[2],
        "primary_scope": aggregate(pooled_records, PRIMARY_DOMAINS),
        "filesystem_only": aggregate(pooled_records, (EXCLUDED_DOMAIN,)),
    })

print(f"\n=== PRIMARY SCOPE (4 domains: {', '.join(PRIMARY_DOMAINS)}) ===\n")
header = f"{'arm':24s} {'model':14s} {'n':>3s} {'task':>7s} {'future':>7s} {'safety':>7s} {'reuse':>7s} {'repair':>7s} {'viol':>5s}"
print(header)
print("-" * len(header))

for cell in sorted(cells, key=lambda c: (c["arm"] != "statewise_v2_retrieval", c["arm"], c["model"])):
    p = cell["primary_scope"]
    def fmt(k):
        v = p.get(k)
        return f"{v:7.4f}" if isinstance(v, (int, float)) else f"{'-':>7s}"
    print(
        f"{cell['arm']:24s} {cell['model']:14s} {p.get('sequences', 0):3d} "
        f"{fmt('task_success_rate')} {fmt('future_task_success_rate')} "
        f"{fmt('future_task_safety_rate')} {fmt('state_reuse_rate')} "
        f"{fmt('t1_repaired_contract_satisfied')} "
        f"{p.get('cumulative_safety_violations', '-'):>5} "
    )

print(f"\n=== FILESYSTEM-ONLY (excluded from primary scope) ===\n")
print("arm                      model            n    task  future  safety   reuse  repair  viol")
print("-" * 90)
for cell in sorted(cells, key=lambda c: (c["arm"] != "statewise_v2_retrieval", c["arm"], c["model"])):
    f = cell["filesystem_only"]
    if not f or f.get("sequences", 0) == 0:
        continue
    def fmt(k):
        v = f.get(k)
        return f"{v:7.4f}" if isinstance(v, (int, float)) else f"{'-':>7s}"
    print(
        f"{cell['arm']:24s} {cell['model']:14s} {f.get('sequences', 0):3d} "
        f"{fmt('task_success_rate')} {fmt('future_task_success_rate')} "
        f"{fmt('future_task_safety_rate')} {fmt('state_reuse_rate')} "
        f"{fmt('t1_repaired_contract_satisfied')} "
        f"{f.get('cumulative_safety_violations', '-'):>5}"
    )

OUT.write_text(json.dumps({"cells": cells, "attrition": attrition}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nwrote {OUT.relative_to(ROOT)}")
