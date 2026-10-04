from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT.parent / 'statewise'
RQ4_SOURCE = Path(
    'runs/formal_v10_rq4_ablations150_gpt56sol_20260822_r1'
    r"\pilot_summary.json"
)
PRIMARY = (
    ROOT / 'paper_experiments/results/shared/permission_matched_v10_all_arms_20260819.xlsx'
)
CASES = (
    RUNTIME
    / "scaffold/experiments/w1_contract_corrected_v10_permission_enabled_sensitivity"
    / "cases"
)
OUT = ROOT / 'paper_experiments/analysis/answer_policy_20260828/pool.json'
ARM = "statewise_v2_contract_corrected_typedfix"


def main() -> None:
    records = pd.DataFrame(
        json.loads(RQ4_SOURCE.read_text(encoding="utf-8"))["records"]
    )
    full = records[records.arm == ARM].copy()
    full["objective"] = (
        (full.risk_adjusted_task_success.astype(bool)
         | full.acceptable_safe_terminal.astype(bool))
        & ~full.safety_violation.astype(bool)
    )
    asked = full[full.questions > 0]
    print("StateWise episodes: %d ; asked a question in %d"
          % (len(full), len(asked)))
    print("objective correct among asked: %d/%d"
          % (int(asked.objective.sum()), len(asked)))
    print("repair correct among asked   : %d/%d"
          % (int(asked.repair_correct.fillna(False).astype(bool).sum()),
             len(asked)))

    head = pd.ExcelFile(PRIMARY).parse("Combined_Episodes")
    meta = head.drop_duplicates("case_id").set_index("case_id")

    rows = []
    for case_id in sorted(asked.case_id):
        path = CASES / f"{case_id}.json"
        if not path.is_file():
            raise SystemExit("pool case absent from the run snapshot: %s"
                             % case_id)
        case = json.loads(path.read_text(encoding="utf-8"))
        rows.append({
            "case_id": case_id,
            "domain": case["domain"],
            "memory_key": case["memory_key"],
            "operator": case.get("corruption_operator"),
            "expected_behavior": str(meta.loc[case_id, "expected_behavior"]),
            "impact": (case.get("difficulty") or {}).get("impact"),
            "truth_value": (case.get("ground_truth_state") or {}).get("value"),
            "corrupted_value": (case.get("corrupted_state") or {}).get("value"),
        })
    frame = pd.DataFrame(rows)
    print()
    print("pool composition:")
    print("  expected_behavior: %s" % frame.expected_behavior.value_counts().to_dict())
    print("  domains          : %s" % frame.domain.value_counts().to_dict())
    print("  memory keys      : %s" % frame.memory_key.value_counts().to_dict())
    print("  operators        : %s" % frame.operator.value_counts().to_dict())


    same = frame[frame.truth_value == frame.corrupted_value]
    if len(same):
        raise SystemExit(
            "these cases have corrupted == truth, so a wrong answer would be "
            "indistinguishable from a correct one: %s"
            % same.case_id.tolist()
        )
    print("  all %d cases have a corrupted value distinct from the truth"
          % len(frame))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "pool_id": "answer_policy_asking_21_v1",
        "selection_rule": (
            "StateWise issued >=1 developer question in "
            "formal_v10_rq4_ablations150_gpt56sol_20260822_r1"
        ),
        "arm": ARM,
        "case_count": len(frame),
        "control_ceiling": {
            "objective_correct": int(asked.objective.sum()),
            "of": len(asked),
        },
        "case_ids": frame.case_id.tolist(),
        "cases": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print()
    print("wrote %s" % OUT)


if __name__ == "__main__":
    main()
