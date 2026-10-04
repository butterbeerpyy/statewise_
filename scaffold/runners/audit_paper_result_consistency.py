from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / 'paper_experiments/results'
PAPER = ROOT / "paper/fse2027/sections/evaluation.tex"
LIMITATIONS = ROOT / "paper/fse2027/sections/limitations.tex"
MAIN = ROOT / "paper/fse2027/main.tex"
OUTPUT = RESULTS / "shared/PAPER_RESULT_CONSISTENCY_AUDIT.json"
SEMANTIC_AUDIT = RESULTS / "shared/audit/USER_PRIVATE_SEMANTICS_FORMAL_V9_AUDIT.md"
PERMISSION_SENSITIVITY = RESULTS / "shared/PERMISSION_ENABLED_SENSITIVITY_V10.xlsx"
PERMISSION_SENSITIVITY_AUDIT = (
    RESULTS / "shared/audit/PERMISSION_ENABLED_SENSITIVITY_V10_AUDIT.json"
)
FAILURE_ANALYSIS = ROOT / "paper/fse2027/sections/failure_analysis.tex"
ANNOTATION_AGREEMENT = RESULTS / "shared/annotation_b_v9/agreement_report.json"


def records(path: Path, sheet_name: str) -> list[dict[str, Any]]:
    sheet = load_workbook(path, read_only=True, data_only=True)[sheet_name]
    values = list(sheet.values)
    headers = list(values[0])
    return [dict(zip(headers, row)) for row in values[1:]]


def table_block(text: str, label: str) -> str:
    label_position = text.index(f"\\label{{{label}}}")
    start = text.rfind("\\begin{table}", 0, label_position)
    end = text.index("\\end{table}", label_position) + len("\\end{table}")
    return text[start:end]


def add(checks: list[dict[str, Any]], name: str, passed: bool, detail: str) -> None:
    checks.append({"check": name, "passed": bool(passed), "detail": detail})


def main() -> int:
    evaluation = PAPER.read_text(encoding="utf-8")
    normalized_evaluation = " ".join(evaluation.split())
    limitations = LIMITATIONS.read_text(encoding="utf-8")
    main_tex = MAIN.read_text(encoding="utf-8")
    rq1 = records(RESULTS / "rq1/rq1_results.xlsx", "Paper_Table")
    rq2 = records(RESULTS / "rq2/rq2_results.xlsx", "Paper_Table")
    rq3 = records(RESULTS / "rq3/rq3_results.xlsx", "Paper_Table")
    rq4 = records(RESULTS / "rq4/rq4_results.xlsx", "Paper_Table")
    rq5 = records(RESULTS / "rq5/rq5_results.xlsx", "Paper_Comparison")
    rq1_episodes = records(RESULTS / "rq1/rq1_results.xlsx", "Episode_Data")
    rq3_episodes = records(RESULTS / "rq3/rq3_results.xlsx", "Episode_Data")
    checks: list[dict[str, Any]] = []

    statewise = {
        "rq1": next(row for row in rq1 if row["method"] == "StateWise"),
        "rq3": next(row for row in rq3 if row["method"] == "StateWise"),
        "rq4": next(row for row in rq4 if row["method"] == "StateWise"),
    }
    signatures = {
        name: (
            row.get("n"), row.get("objective_correct_n"),
            row.get("objective_correctness"), row.get("action_completed_n"),
            row.get("action_completion"), row.get("safety_violation_n"),
        )
        for name, row in statewise.items()
    }
    add(
        checks,
        "RQ1/RQ3/RQ4 StateWise signature agrees",
        len(set(signatures.values())) == 1,
        json.dumps(signatures, sort_keys=True),
    )
    rq2_signature = {
        row["method"]: (
            row["n"], row["objective_correct_n"], row["action_completed_n"],
            row["safety_violation_n"],
        )
        for row in rq2
    }
    add(
        checks,
        "RQ2 paper table has only the five intended arms",
        rq2_signature == {
            "Corrupted memory": (150, 40, 16, 64),
            "Bare approval": (150, 50, 25, 0),
            "Rationale approval": (150, 62, 38, 0),
            "Generic clarification": (150, 42, 18, 57),
            "StateWise": (150, 126, 101, 0),
        },
        json.dumps(rq2_signature, sort_keys=True),
    )
    add(
        checks,
        "single-task eligibility is 125 SHOULD_ACT / 25 SHOULD_STOP",
        "125 cases are \\textsc{should-act} and 25 are" in evaluation,
        "Corrected formal-v9 eligibility contract.",
    )
    stale_tokens = [
        "135/149 (90.6\\%)", "91/104 (87.5\\%)",
        "over the 105 \\textsc{should-act}",
        "80\\% to 42\\%", "recovers correctness to 91\\%",
    ]
    present = [token for token in stale_tokens if token in evaluation or token in main_tex]
    add(checks, "old evaluator claims absent", not present, json.dumps(present))
    add(
        checks,
        "corrected headline present",
        all(token in evaluation + main_tex for token in [
            "126/150 (84.0\\%)", "101/125 (80.8\\%)",
            "69\\% to 27\\%", "recovers correctness to 84\\%",
        ]),
        "84.0% objective correctness; 80.8% action completion; zero violations.",
    )
    add(
        checks,
        "cost omitted from paper",
        "\\subsection{Cost}" not in evaluation and "tab:cost" not in evaluation,
        "Resource workbook remains supplementary-only.",
    )
    oracle_tables = [
        label for label in ["tab:main", "tab:rq4", "tab:rq5-arms"]
        if "Oracle" in table_block(evaluation, label)
    ]
    add(checks, "Oracle absent from paper-facing result tables", not oracle_tables, json.dumps(oracle_tables))
    add(
        checks,
        "RQ5 canonical primary retained",
        any(row["method"] == "StateWise" and row["sequences"] == 32 for row in rq5),
        "Primary and replication are not pooled.",
    )
    semantic_statewise = [
        row for row in rq1_episodes
        if row["domain"] == "user_private_semantics"
        and row["expected_behavior"] == "SHOULD_ACT"
        and row["arm"] == "statewise_v2_contract_corrected_typedfix"
    ]
    semantic_correct = [
        row for row in rq1_episodes
        if row["domain"] == "user_private_semantics"
        and row["expected_behavior"] == "SHOULD_ACT"
        and row["arm"] == "correct"
    ]
    semantic_sentry = [
        row for row in rq3_episodes
        if row["domain"] == "user_private_semantics"
        and row["expected_behavior"] == "SHOULD_ACT"
        and row["arm"] == "safety_sentry"
    ]
    semantic_signature = {
        "statewise_n": len(semantic_statewise),
        "statewise_correct": sum(bool(row["behaviorally_correct"]) for row in semantic_statewise),
        "statewise_repair_correct": sum(bool(row["repair_correct"]) for row in semantic_statewise),
        "correct_memory_correct": sum(bool(row["behaviorally_correct"]) for row in semantic_correct),
        "safety_sentry_correct": sum(bool(row["behaviorally_correct"]) for row in semantic_sentry),
    }
    add(
        checks,
        "semantic permission-path audit matches episode data",
        semantic_signature == {
            "statewise_n": 20,
            "statewise_correct": 0,
            "statewise_repair_correct": 18,
            "correct_memory_correct": 1,
            "safety_sentry_correct": 18,
        },
        json.dumps(semantic_signature, sort_keys=True),
    )
    semantic_reporting_tokens = [
        "arm-specific permission execution" in evaluation,
        "Permission-path comparability" in limitations,
        "not evidence that \\statewise{} fails to understand user" in limitations,
        SEMANTIC_AUDIT.exists(),
    ]
    add(
        checks,
        "semantic limitation is retained in paper and audit artifact",
        all(semantic_reporting_tokens),
        "Frozen scores retained; state reasoning is not conflated with permission execution.",
    )
    sensitivity = records(PERMISSION_SENSITIVITY, "Sensitivity_Summary")[0]
    sensitivity_audit = json.loads(
        PERMISSION_SENSITIVITY_AUDIT.read_text(encoding="utf-8")
    )
    sensitivity_signature = {
        "n": sensitivity["n"],
        "formal_v9_completed": sensitivity["formal_v9_action_completed_n"],
        "permission_enabled_completed": sensitivity["permission_enabled_completed_n"],
        "paired_improved": sensitivity["paired_improved_n"],
        "violations": sensitivity["safety_violation_n"],
        "reporting_status": sensitivity["reporting_status"],
        "audit_status": sensitivity_audit["status"],
    }
    add(
        checks,
        "permission-enabled semantic sensitivity is exact and non-headline",
        sensitivity_signature == {
            "n": 20,
            "formal_v9_completed": 0,
            "permission_enabled_completed": 18,
            "paired_improved": 18,
            "violations": 0,
            "reporting_status": "sensitivity_only_not_primary_heldout",
            "audit_status": "VALID",
        }
        and "completes 18/20 cases (versus 0/20 in the frozen run)" in normalized_evaluation
        and "construct-validity evidence rather than a new" in normalized_evaluation,
        json.dumps(sensitivity_signature, sort_keys=True),
    )
    statewise_episode_metrics = next(
        row for row in records(RESULTS / "rq1/rq1_results.xlsx", "Arm_Summary")
        if row["arm"] == "statewise_v2_contract_corrected_typedfix"
    )
    attribution_signature = {
        "evaluable_n": statewise_episode_metrics["attribution_evaluable_n"],
        "coverage": statewise_episode_metrics["attribution_coverage_rate"],
        "precision": statewise_episode_metrics["mean_attribution_precision"],
        "recall": statewise_episode_metrics["mean_attribution_recall"],
        "f1": statewise_episode_metrics["mean_attribution_f1"],
    }
    add(
        checks,
        "attribution score is reported with evaluability coverage",
        attribution_signature == {
            "evaluable_n": 14,
            "coverage": 14 / 150,
            "precision": 1,
            "recall": 1,
            "f1": 1,
        }
        and "Only 14/150 StateWise episodes (9.3\\%)" in normalized_evaluation
        and "precision, recall, and F1 are all 1.00" in normalized_evaluation,
        json.dumps(attribution_signature, sort_keys=True),
    )


    if ANNOTATION_AGREEMENT.exists():
        agreement_report = json.loads(ANNOTATION_AGREEMENT.read_text(encoding="utf-8"))
        agreement = agreement_report.get("agreement") or {}
        failure_text = " ".join(FAILURE_ANALYSIS.read_text(encoding="utf-8").split())
        limitations_text = " ".join(limitations.split())
        behavior_rate = agreement.get("behavior_exact_rate")
        support_rate = agreement.get("support_set_exact_rate")
        claims_present = (
            agreement_report.get("status") == "COMPLETE"
            and behavior_rate is not None
            and f"{behavior_rate * 100:.1f}\\%" in failure_text
            and f"{support_rate * 100:.1f}\\%" in failure_text
        )
        add(
            checks,
            "independent annotation agreement matches the scored report",
            claims_present,
            json.dumps(
                {
                    "status": agreement_report.get("status"),
                    "completed_items": agreement_report.get("completed_items"),
                    "behavior_exact_rate": behavior_rate,
                    "support_set_exact_rate": support_rate,
                    "behavior_cohen_kappa": agreement.get("behavior_cohen_kappa"),
                },
                sort_keys=True,
            ),
        )


        add(
            checks,
            "one-directional annotation disagreement is disclosed",
            "one way" in limitations_text or "one-directional" in failure_text,
            "Directional asymmetry stated alongside the agreement rate.",
        )
    else:
        add(
            checks,
            "independent annotation agreement matches the scored report",
            False,
            "agreement_report.json is absent; annotation B has not been scored.",
        )

    payload = {
        "status": "VALID" if all(check["passed"] for check in checks) else "INVALID",
        "canonical_sources": {
            "rq1": 'paper_experiments/results/rq1/rq1_results.xlsx',
            "rq2": 'paper_experiments/results/rq2/rq2_results.xlsx',
            "rq3": 'paper_experiments/results/rq3/rq3_results.xlsx',
            "rq4": 'paper_experiments/results/rq4/rq4_results.xlsx',
            "rq5": 'paper_experiments/results/rq5/rq5_results.xlsx',
            "permission_sensitivity": (
                'paper_experiments/results/shared/PERMISSION_ENABLED_SENSITIVITY_V10.xlsx'
            ),
        },
        "checks": checks,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
