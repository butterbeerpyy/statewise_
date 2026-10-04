import collections
import csv
import json
from pathlib import Path

import openpyxl


ROOT = Path(__file__).resolve().parent


def sheet_rows(path, sheet):
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    values = workbook[sheet].iter_rows(values_only=True)
    headers = next(values)
    rows = [dict(zip(headers, row)) for row in values]
    workbook.close()
    return rows


def csv_rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    book = ROOT / "paper_experiments/results/shared/permission_matched_v10_all_arms_20260819.xlsx"
    rows = sheet_rows(book, "Combined_Episodes")
    groups = collections.defaultdict(list)
    for row in rows:
        groups[row["arm"]].append(row)
    expected = {
        "correct": (121, 0),
        "corrupted": (58, 64),
        "no_memory": (68, 14),
        "generic_clarification": (47, 57),
    }
    checks = []
    for arm, (correct, unsafe) in expected.items():
        cohort = groups[arm]
        actual = (sum(bool(row["behaviorally_correct"]) for row in cohort), sum(bool(row["safety_violation"]) for row in cohort))
        checks.append({"claim": arm + " primary historical outcomes", "expected": [150, correct, unsafe], "actual": [len(cohort), *actual], "passed": len(cohort) == 150 and actual == (correct, unsafe)})
    ablations = csv_rows(ROOT / "paper_experiments/analysis/restructure_audit_20260829/table_component_appendix_7arm.csv")
    full = next(row for row in ablations if row["variant"] == "Full StateWise")
    checks.append({"claim": "Locked seven-arm historical Full StateWise", "expected": [140, 150], "actual": [int(full["safe_completion_numerator"]), int(full["safe_completion_denominator"])], "passed": int(full["safe_completion_numerator"]) == 140 and int(full["safe_completion_denominator"]) == 150})
    generalization = csv_rows(ROOT / "paper_experiments/analysis/rq6_generalization_20260909/main150_rq6_case_metrics.csv")
    checks.append({"claim": "Generalization historical total and correct counts", "expected": [150, 140], "actual": [len(generalization), sum(int(row["overall_correct"]) for row in generalization)], "passed": len(generalization) == 150 and sum(int(row["overall_correct"]) for row in generalization) == 140})
    output = {"scope": "Checks selected historical paper anchors against the supplied workbooks and audit tables. This does not evaluate the revised baseline, certify unrecorded historical dependencies, or validate every manuscript claim.", "checks": checks, "passed": all(check["passed"] for check in checks)}
    (ROOT / "paper_table_checks.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output))
    if not output["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
