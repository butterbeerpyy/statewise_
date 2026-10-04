import glob
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scaffold.runners import validate_closure

paths = sorted(glob.glob(str(ROOT / "scaffold" / "cases" / "case_easy_*.json")))
print(f"checking {len(paths)} easy-wave cases")
failures = []
for path in paths:
    case = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    record = validate_closure.validate(case)
    flag = "PASS" if record["passed"] else "FAIL"
    print(f"[{flag}] {record['case_id']}", flush=True)
    if not record["passed"]:
        failures.append(record)

print(f"\nsummary={len(paths) - len(failures)}/{len(paths)} passed")
for record in failures:
    print("\n=== " + str(record["case_id"]))
    print("schema_errors:", record.get("schema_errors"))
    print("runtime_error:", record.get("runtime_error"))
    print("reset_equivalent:", record.get("reset_equivalent"))
    print("terminal:", record.get("terminal"))
    print("safe:", record.get("safe"))
    print("no_configuration_errors:", record.get("no_configuration_errors"))
    for run in record.get("runs", [])[:1]:
        print("status:", run["status"])
        print("oracle:", json.dumps(run["oracle"], ensure_ascii=False)[:900])
        print("diff:", json.dumps(run["diff"], ensure_ascii=False)[:600])
sys.exit(1 if failures else 0)
