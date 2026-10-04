import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs" / "rq5_longitudinal"
OUT = ROOT / "runs" / "rq5_matrix_aggregated.json"


BASELINE_ARMS = (
    "correct", "corrupted", "no_memory", "auto_execute", "bare_approval",
    "rationale_approval", "generic_clarification", "safety_sentry",
    "memlineage_trust", "oracle_statewise",
)
EXPECTED_SHARDS = [f"rq5v2_base_{arm}_gpt56sol" for arm in BASELINE_ARMS] + [
    "rq5v2_method_deepseek",
    "rq5v2_method_qwen",
]

shards = [RUNS / name for name in EXPECTED_SHARDS if (RUNS / name).is_dir()]
missing = [name for name in EXPECTED_SHARDS if not (RUNS / name).is_dir()]
if not shards:
    print("No matrix shards found under", RUNS, file=sys.stderr)
    sys.exit(1)

print(f"Found {len(shards)}/{len(EXPECTED_SHARDS)} expected shards")
if missing:
    print("MISSING shards:", missing)

unexpected = sorted(
    p.name for p in RUNS.glob("rq5v2_*")
    if p.is_dir() and p.name not in EXPECTED_SHARDS
)
if unexpected:
    print("\nIGNORED (prefix match but not part of this matrix):")
    for name in unexpected:
        print("  ", name)


def model_tag(run_id, arm):

    if run_id.startswith("rq5v2_method_"):
        return run_id[len("rq5v2_method_"):]
    rest = run_id[len("rq5v2_base_"):] if run_id.startswith("rq5v2_base_") else run_id
    if rest.startswith(arm + "_"):
        return rest[len(arm) + 1:]
    return rest


rows = []
incomplete = []
for shard_dir in shards:
    summary_path = shard_dir / "longitudinal_summary.json"
    if not summary_path.exists():
        incomplete.append(shard_dir.name)
        continue

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    status = summary.get("status")


    if status not in ("COMPLETE", "COMPLETE_WITH_FAILURES"):
        incomplete.append(f"{shard_dir.name} (status={status})")
        continue


    statuses = summary.get("failed_episode_statuses") or {}
    failed_count = sum(statuses.values()) if isinstance(statuses, dict) else len(statuses)
    for entry in summary.get("table", []):
        rows.append({
            "run_id": shard_dir.name,
            "status": status,
            "arm": entry["arm"],
            "model": model_tag(shard_dir.name, entry["arm"]),
            "sequences": entry["sequences"],
            "task_success_rate": entry["task_success_rate"],
            "future_task_success_rate": entry.get("future_task_success_rate"),
            "future_task_safety_rate": entry.get("future_task_safety_rate"),
            "state_handoff_integrity_rate": entry.get("state_handoff_integrity_rate"),
            "state_reuse_rate": entry.get("state_reuse_rate"),
            "repeated_intervention_rate": entry.get("repeated_intervention_rate"),
            "cumulative_questions": entry.get("cumulative_questions"),
            "cumulative_permission_interactions": entry.get(
                "cumulative_permission_interactions"
            ),
            "cumulative_safety_violations": entry.get("cumulative_safety_violations"),
            "t1_repair_success_rate": entry.get("t1_repair_success_rate"),
            "failed_episodes": failed_count,
            "failed_episode_statuses": statuses,
            "provider_profile": (summary.get("provider_preflight") or {}).get(
                "selected_profile"
            ),
        })


        by_domain = collections.defaultdict(list)
        for record in summary.get("sequence_arm_results") or []:
            if record.get("arm") != entry["arm"]:
                continue
            sequence_id = record.get("sequence_id", "")
            domain = sequence_id.split("_")[1] if "_" in sequence_id else "unknown"
            by_domain[domain].append(record)
        rows[-1]["per_domain_task_success"] = {
            domain: round(
                sum(r.get("task_success_rate", 0) for r in items) / len(items), 4
            )
            for domain, items in sorted(by_domain.items())
        }


POOLED_METHOD = ["rq5_v2_full40_gpt56sol", "rq5_v2_full40_gpt56sol_part2"]
pooled_records = []
pooled_missing = [
    r for r in POOLED_METHOD if not (RUNS / r / "longitudinal_summary.json").exists()
]
if not pooled_missing:
    for run_id in POOLED_METHOD:
        summary = json.loads(
            (RUNS / run_id / "longitudinal_summary.json").read_text(encoding="utf-8")
        )
        pooled_records.extend(summary.get("sequence_arm_results") or [])


def mean(values):
    values = [v for v in values if isinstance(v, (int, float))]
    return round(sum(values) / len(values), 6) if values else None


if pooled_records:
    by_domain = collections.defaultdict(list)
    for record in pooled_records:
        sequence_id = record.get("sequence_id", "")
        domain = sequence_id.split("_")[1] if "_" in sequence_id else "unknown"
        by_domain[domain].append(record)
    rows.append({
        "run_id": "+".join(POOLED_METHOD),
        "arm": "statewise_v2_retrieval",
        "model": "gpt56sol",
        "sequences": len(pooled_records),
        "task_success_rate": mean(r.get("task_success_rate") for r in pooled_records),
        "future_task_success_rate": mean(
            r.get("future_task_success_rate") for r in pooled_records
        ),
        "future_task_safety_rate": mean(
            r.get("future_task_safety_rate") for r in pooled_records
        ),
        "state_handoff_integrity_rate": mean(
            r.get("state_handoff_integrity_rate") for r in pooled_records
        ),
        "state_reuse_rate": mean(r.get("state_reuse_rate") for r in pooled_records),


        "t1_repair_success_rate": mean(
            bool(r.get("t1_repaired_contract_satisfied")) for r in pooled_records
        ),
        "cumulative_safety_violations": sum(
            int(r.get("cumulative_safety_violations") or 0) for r in pooled_records
        ),
        "status": "COMPLETE",
        "failed_episodes": 0,
        "provider_profile": "api_02_rq5_session",
        "note": "pooled across two run_ids; sequence-level mean, not a shard summary",
        "per_domain_task_success": {
            domain: round(
                sum(r.get("task_success_rate", 0) for r in items) / len(items), 4
            )
            for domain, items in sorted(by_domain.items())
        },
    })

if incomplete:
    print(f"\nSTILL RUNNING / INCOMPLETE ({len(incomplete)}):")
    for name in incomplete:
        print("  ", name)

print(f"\n=== {len(rows)} completed (arm, model) cells ===")
header = f"{'arm':24s} {'model':10s} {'n':>3s} {'task':>7s} {'future':>7s} {'safety':>7s} {'reuse':>7s} {'repair':>7s} {'viol':>5s} {'fail':>4s}"
print(header)
print("-" * len(header))
for row in sorted(rows, key=lambda r: (r["arm"] != "statewise_v2_retrieval", r["arm"], r["model"])):
    def fmt(key):
        value = row.get(key)
        return f"{value:7.4f}" if isinstance(value, (int, float)) else f"{'-':>7s}"
    violations = row.get("cumulative_safety_violations")
    print(
        f"{row['arm']:24s} {row['model']:10s} {row['sequences']:3d} "
        f"{fmt('task_success_rate')} {fmt('future_task_success_rate')} "
        f"{fmt('future_task_safety_rate')} {fmt('state_reuse_rate')} "
        f"{fmt('t1_repair_success_rate')} "
        f"{violations if violations is not None else '-':>5} "
        f"{row['failed_episodes']:4d}"
    )

print("\n=== per-domain task success (method arms) ===")
for row in rows:
    if row["arm"] != "statewise_v2_retrieval":
        continue
    print(f"  {row['model']}: {row['per_domain_task_success']}")

OUT.write_text(
    json.dumps(
        {"rows": rows, "incomplete": incomplete, "shards_found": len(shards)},
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print(f"\nwrote {OUT.relative_to(ROOT)}")
