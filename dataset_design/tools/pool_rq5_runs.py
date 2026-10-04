import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs" / "rq5_longitudinal"

run_ids = sys.argv[1:] or [
    "rq5_v2_full40_gpt56sol",
    "rq5_v2_full40_gpt56sol_part2",
]

summaries = {}
for run_id in run_ids:
    path = RUNS / run_id / "longitudinal_summary.json"
    summaries[run_id] = json.loads(path.read_text(encoding="utf-8"))


provenance = {}
for run_id in run_ids:
    manifest = json.loads((RUNS / run_id / "manifest.json").read_text(encoding="utf-8"))
    config = manifest["experiment_config"]
    provenance[run_id] = {
        "model": config.get("model"),
        "fake_api": config.get("fake_api"),
        "arms": tuple(config.get("arms") or ()),
        "dataset": (config.get("dataset") or {}).get("composite_sha256"),
    }
distinct = {tuple(sorted(item.items())) for item in provenance.values()}
print("provenance identical across runs:", len(distinct) == 1)
for run_id, item in provenance.items():
    print(f"  {run_id}: {item}")
if len(distinct) != 1:
    raise SystemExit("refusing to pool: runs differ in model, arm, dataset or fake flag")


def sequence_records(summary):

    for key in ("sequence_arm_results", "sequences", "per_sequence", "sequence_records"):
        value = summary.get(key)
        if isinstance(value, list) and value:
            return value
    return []


records = []
seen_ids = set()
for run_id in run_ids:
    for record in sequence_records(summaries[run_id]):
        sid = record.get("sequence_id")
        if sid in seen_ids:
            raise SystemExit(f"duplicate sequence across runs: {sid}")
        seen_ids.add(sid)
        records.append({"run_id": run_id, **record})

print(f"\npooled sequences: {len(records)}")
if not records:
    print("summary keys:", sorted(summaries[run_ids[0]]))
    raise SystemExit("no per-sequence records found; inspect summary shape above")

METRICS = [
    "task_success_rate",
    "future_task_success_rate",
    "future_task_safety_rate",
    "state_handoff_integrity_rate",
    "state_reuse_rate",
    "t1_repair_success_rate",
]


def mean(values):
    values = [v for v in values if isinstance(v, (int, float))]
    return round(sum(values) / len(values), 4) if values else None


def domain_of(record):
    sid = record.get("sequence_id") or ""
    parts = sid.split("_")
    return parts[1] if len(parts) > 2 else "unknown"


print("\n=== pooled overall ===")
for metric in METRICS:
    print(f"{metric}: {mean(r.get(metric) for r in records)}")

print("\n=== by domain ===")
by_domain = collections.defaultdict(list)
for record in records:
    by_domain[domain_of(record)].append(record)
for domain in sorted(by_domain):
    group = by_domain[domain]
    line = " ".join(
        f"{metric.replace('_rate', '')}={mean(r.get(metric) for r in group)}"
        for metric in ("task_success_rate", "t1_repair_success_rate", "state_reuse_rate")
    )
    print(f"{domain:12s} n={len(group):2d} {line}")
