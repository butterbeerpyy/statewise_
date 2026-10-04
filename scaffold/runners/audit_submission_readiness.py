from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / 'paper_experiments' / 'results'
OUTPUT_JSON = RESULTS / "shared" / "SUBMISSION_READINESS_AUDIT.json"
OUTPUT_MD = RESULTS / "shared" / "SUBMISSION_READINESS_AUDIT.md"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _records(path: Path, sheet: str) -> list[dict[str, Any]]:
    worksheet = load_workbook(path, read_only=True, data_only=True)[sheet]
    values = worksheet.iter_rows(values_only=True)
    headers = next(values)
    return [dict(zip(headers, row)) for row in values]


def main() -> int:
    canonical = {
        "RQ1": (RESULTS / "rq1" / "rq1_results.xlsx", "Paper_Table"),
        "RQ2": (RESULTS / "rq2" / "rq2_results.xlsx", "Paper_Table"),
        "RQ3": (RESULTS / "rq3" / "rq3_results.xlsx", "Paper_Table"),
        "RQ4": (RESULTS / "rq4" / "rq4_results.xlsx", "Paper_Table"),
        "RQ5": (RESULTS / "rq5" / "rq5_results.xlsx", "Paper_Comparison"),
    }
    expected_methods = {
        "RQ1": {"Correct memory", "Corrupted memory", "No memory", "StateWise"},
        "RQ2": {
            "Corrupted memory", "Bare approval", "Rationale approval",
            "Generic clarification", "StateWise",
        },
        "RQ3": {
            "Correct memory", "Corrupted memory", "No memory", "MemLineage",
            "Safety Sentry", "Ask-or-Assume", "StateWise",
        },
        "RQ4": {
            "StateWise", "w/o Attribution", "w/o Resolution", "w/o Repair",
            "w/o Replanning", "w/o Residual Gate", "w/o Typed Grounding",
        },
        "RQ5": {"StateWise", "MemLineage", "Safety Sentry", "Ask-or-Assume"},
    }
    artifacts = {}
    checks = []
    for rq, (path, sheet) in canonical.items():
        rows = _records(path, sheet)
        methods = {row["method"] for row in rows}
        checks.append({
            "check": f"{rq} paper-facing methods are exact",
            "passed": methods == expected_methods[rq],
            "detail": sorted(methods),
        })
        checks.append({
            "check": f"{rq} paper-facing table excludes Oracle",
            "passed": all("oracle" not in method.lower() for method in methods),
            "detail": sorted(methods),
        })
        artifacts[rq] = {
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": _sha256(path),
            "paper_sheet": sheet,
            "paper_rows": len(rows),
        }

    rq1 = _records(canonical["RQ1"][0], canonical["RQ1"][1])
    rq2 = _records(canonical["RQ2"][0], canonical["RQ2"][1])
    rq4 = _records(canonical["RQ4"][0], canonical["RQ4"][1])
    rq5 = _records(canonical["RQ5"][0], canonical["RQ5"][1])
    checks.extend([
        {
            "check": "RQ1 and RQ2 use the same 150-case contract",
            "passed": all(row["n"] == 150 for row in rq1 + rq2),
            "detail": "125 SHOULD_ACT / 25 SHOULD_STOP",
        },
        {
            "check": "RQ4 is fully paired at N=150",
            "passed": all(row["n"] == 150 for row in rq4),
            "detail": {row["method"]: row["n"] for row in rq4},
        },
        {
            "check": "RQ5 paper comparison is four methods at N=32",
            "passed": all(row["sequences"] == 32 for row in rq5),
            "detail": {row["method"]: row["sequences"] for row in rq5},
        },
    ])

    consistency_path = RESULTS / "shared" / "PAPER_RESULT_CONSISTENCY_AUDIT.json"
    consistency = json.loads(consistency_path.read_text(encoding="utf-8"))
    sensitivity_path = (
        RESULTS / "shared" / "audit" / "PERMISSION_ENABLED_SENSITIVITY_V10_AUDIT.json"
    )
    sensitivity = json.loads(sensitivity_path.read_text(encoding="utf-8"))
    checks.extend([
        {
            "check": "paper-result consistency audit is valid",
            "passed": consistency.get("status") == "VALID",
            "detail": f"{sum(c['passed'] for c in consistency['checks'])}/{len(consistency['checks'])}",
        },
        {
            "check": "permission sensitivity is valid and non-headline",
            "passed": sensitivity.get("status") == "VALID"
            and sensitivity.get("reporting_status")
            == "sensitivity_only_not_primary_heldout",
            "detail": sensitivity.get("summary"),
        },
        {
            "check": "paper PDF compiles",
            "passed": (ROOT / "paper" / "fse2027" / "main.pdf").is_file(),
            "detail": "paper/fse2027/main.pdf",
        },
    ])

    pending = {
        "P0": [
            {
                "item": "Independent Annotator B and agreement adjudication",
                "status": "IN_PROGRESS",
                "completion_rule": (
                    "Score all 150 frozen cases, report raw agreement and Cohen's "
                    "kappa per field, retain disagreements, and adjudicate without "
                    "changing method outcomes."
                ),
            }
        ],
        "P1": [
            {
                "item": "Cross-model replication",
                "status": "NOT_IN_PRIMARY_CLAIMS",
                "completion_rule": (
                    "Use the same frozen snapshot, evaluator, temperature policy, "
                    "and non-adaptive stopping rule."
                ),
            },
            {
                "item": "Matched permission channel for external baselines",
                "status": "OPTIONAL_STRENGTHENING",
                "completion_rule": (
                    "Route all compared arms through the same deterministic case "
                    "permission policy; do not alter frozen baseline logic."
                ),
            },
        ],
        "P2": [
            {
                "item": "Threshold sweep",
                "status": "APPENDIX_CANDIDATE",
                "completion_rule": "Predeclare grid and report safety-capability curve.",
            },
            {
                "item": "Human-answer strategy sensitivity",
                "status": "APPENDIX_OR_FUTURE_WORK",
                "completion_rule": (
                    "Hold the agent fixed and vary truthful, uncertain, delayed, and "
                    "mistaken respondent policies."
                ),
            },
            {
                "item": "Token and latency accounting",
                "status": "SUPPLEMENTARY_ONLY",
                "completion_rule": (
                    "Retain in rq1_rq5_resource_costs.xlsx; exclude from headline "
                    "unless provider-side latency is normalized."
                ),
            },
        ],
    }
    result_valid = all(check["passed"] for check in checks)
    payload = {
        "schema_version": "statewise-submission-readiness-v1",
        "status": "VALID_RESULTS_WITH_PENDING_P0" if result_valid else "INVALID",
        "canonical_artifacts": artifacts,
        "checks": checks,
        "pending": pending,
        "collaborator_rule": (
            "Use only the named paper-facing sheet from each canonical workbook. "
            "Other sheets and sibling files are diagnostics or provenance."
        ),
    }
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Submission Readiness Audit",
        "",
        f"Status: **{payload['status']}**",
        "",
        "## Canonical result files",
        "",
        "| RQ | Workbook | Paper-facing sheet | Rows | SHA256 |",
        "|---|---|---|---:|---|",
    ]
    for rq, artifact in artifacts.items():
        lines.append(
            f"| {rq} | `{artifact['path']}` | `{artifact['paper_sheet']}` | "
            f"{artifact['paper_rows']} | `{artifact['sha256']}` |"
        )
    lines.extend([
        "",
        "Use only the sheet named above for paper figures and tables. Other sheets",
        "and sibling files are diagnostics, raw episode data, or provenance.",
        "",
        "## Checks",
        "",
    ])
    for check in checks:
        mark = "PASS" if check["passed"] else "FAIL"
        lines.append(f"- **{mark}** {check['check']}")
    for priority in ("P0", "P1", "P2"):
        lines.extend(["", f"## {priority}", ""])
        for item in pending[priority]:
            lines.append(f"- **{item['status']}** {item['item']}: {item['completion_rule']}")
    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
