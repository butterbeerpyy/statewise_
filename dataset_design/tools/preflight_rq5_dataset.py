import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scaffold.statewise.evaluation.longitudinal_runtime import (
    materialize_case,
    smoke_preflight,
)
from scaffold.statewise.evaluation.longitudinal_schema import load_dataset

directory = pathlib.Path(sys.argv[1])
sequences = load_dataset(directory)
total = sum(len(s["tasks"]) for s in sequences)
print(f"preflighting {len(sequences)} sequences / {total} tasks in {directory}")

failures = []
for sequence in sequences:
    for task in sequence["tasks"]:
        case = materialize_case(sequence, task)
        report = smoke_preflight(case)
        if not report.get("ok"):
            failures.append((sequence["sequence_id"], task["task_id"], report))
    flag = "ok" if not any(f[0] == sequence["sequence_id"] for f in failures) else "FAIL"
    print(f"[{flag}] {sequence['sequence_id']}", flush=True)

print(f"\nsummary={total - len(failures)}/{total} tasks executable")
for sid, tid, report in failures[:10]:
    print(f"\n=== {sid}/{tid}")
    print("error_type:", report.get("error_type"))
    print("message:", report.get("message"))
    if report.get("oracle") is not None:
        print("oracle:", json.dumps(report["oracle"], ensure_ascii=False)[:800])
if len(failures) > 10:
    print(f"\n(+{len(failures) - 10} more failures not shown)")
sys.exit(1 if failures else 0)
