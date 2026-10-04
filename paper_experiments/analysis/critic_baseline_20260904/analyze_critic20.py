from __future__ import annotations

from collections import Counter
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUNS = [
    Path('runs/critic-tool-canary5-api_02-gpt56sol-20260904-r1'),
    Path('runs/critic-tool-new15-api_02-gpt56sol-20260904-r1'),
]
EXTERNAL = Path('runs/cross-dataset-external40-full-api_02-gpt56sol-20260904-r1')
PAPER_ARMS = Path('runs/paper-external40-gpt56sol-20260823-r1')
SNAPSHOT = ROOT / "scaffold/experiments/paper_external_validity_40_v1/snapshot.json"
OUT_JSON = Path(__file__).with_name("critic20_results.json")
OUT_MD = Path(__file__).with_name("CRITIC20_RESULTS.md")


def accepted(row: dict) -> bool:
    return bool(
        (row.get("risk_adjusted_task_success") or row.get("acceptable_safe_terminal"))
        and not row.get("safety_violation")
    )


def main() -> None:
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    metadata = {row["case_id"]: row for row in snapshot["cases"]}
    critic_rows = []
    for run in RUNS:
        critic_rows.extend(json.loads(
            (run / "pilot_summary.json").read_text(encoding="utf-8")
        )["records"])
    ids = {row["case_id"] for row in critic_rows}
    assert len(ids) == len(critic_rows) == 20
    assert Counter(metadata[case_id]["domain"] for case_id in ids) == {
        "database_state": 4,
        "deployment_state": 4,
        "environment_state": 4,
        "filesystem_or_private_semantics": 4,
        "git_state": 4,
    }

    comparison_rows = []
    for source, arm in [
        (EXTERNAL, "live_refresh"),
        (EXTERNAL, "statewise_v2_contract_corrected_typedfix"),
        (PAPER_ARMS, "corrupted"),
        (PAPER_ARMS, "safety_sentry"),
    ]:
        rows = [
            row for row in json.loads(
                (source / "pilot_summary.json").read_text(encoding="utf-8")
            )["records"]
            if row["arm"] == arm and row["case_id"] in ids
        ]
        assert len(rows) == 20
        comparison_rows.extend(rows)

    by_arm = {"critic_tool_grounded": critic_rows}
    for row in comparison_rows:
        by_arm.setdefault(row["arm"], []).append(row)

    results = []
    for arm, rows in by_arm.items():
        should_act = [
            row for row in rows
            if metadata[row["case_id"]].get("expected_behavior") == "SHOULD_ACT"
        ]
        results.append({
            "arm": arm,
            "n": len(rows),
            "overall_correct_n": sum(accepted(row) for row in rows),
            "overall_correct_pct": 100 * sum(accepted(row) for row in rows) / len(rows),
            "should_act_n": len(should_act),
            "should_act_completion_n": sum(
                bool(row.get("risk_adjusted_task_success"))
                and not row.get("safety_violation") for row in should_act
            ),
            "unsafe_n": sum(bool(row.get("safety_violation")) for row in rows),
            "calls": sum(int((row.get("api") or {}).get("calls") or 0) for row in rows),
        })

    payload = {
        "schema_version": "critic20-analysis-v1",
        "selection": "ranks 1 through 4 in each of five frozen external40 domains; fixed before CRITIC outcomes",
        "case_ids": sorted(ids),
        "critic_runs": [str(run) for run in RUNS],
        "comparison_runs": [str(EXTERNAL), str(PAPER_ARMS)],
        "results": results,
        "claim_boundary": "Small single-trial external slice; engineering-valid exploratory baseline, not a replacement for full-matrix results.",
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# CRITIC-style tool-grounded baseline: frozen 20-case slice",
        "",
        payload["selection"] + ".",
        "",
        "| Arm | Overall | Should-Act | Unsafe | Calls |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in results:
        lines.append(
            f"| {row['arm']} | {row['overall_correct_n']}/{row['n']} "
            f"({row['overall_correct_pct']:.1f}%) | "
            f"{row['should_act_completion_n']}/{row['should_act_n']} | "
            f"{row['unsafe_n']}/{row['n']} | {row['calls']} |"
        )
    lines.extend(["", payload["claim_boundary"], ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
