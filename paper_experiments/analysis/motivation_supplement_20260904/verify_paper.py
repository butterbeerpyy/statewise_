from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def main() -> int:
    results = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
    observation = json.loads(
        (ROOT / "experiments" / "observation_swe_chat" / "audit" / "audit_summary.json").read_text(encoding="utf-8")
    )
    motivation = (ROOT / "paper" / "fse2027" / "sections" / "motivation.tex").read_text(encoding="utf-8")
    main_tex = (ROOT / "paper" / "fse2027" / "main.tex").read_text(encoding="utf-8")
    metrics = {row["arm"]: row for row in results["metrics"]}

    assert observation["sampled_sessions"] == 100
    assert observation["raw_positive_sessions"] == 60
    assert observation["structurally_clean_positive_sessions"] == 40
    assert results["refresh_recovery_complete"] is True
    assert results["refresh_recovery_pairing_valid"] is True
    assert len(results["refresh_failed_cells_replaced"]) == 5
    assert results["statewise_correct_repair_semantics"] == {
        "same_semantic_value": 99,
        "missing_old_value": 3,
        "changed_semantic_value": 6,
    }
    assert metrics["refresh_corrupted"]["overall_correct_n"] == 125
    assert metrics["statewise_corrupted"]["overall_correct_n"] == 133
    assert metrics["refresh_correct"]["overall_correct_n"] == 127
    assert metrics["statewise_correct"]["overall_correct_n"] == 132
    assert metrics["vanilla_correct"]["overall_correct_n"] == 106

    required_fragments = (
        "40 survive that structural",
        "83.3\\% with no",
        "88.7\\% with none",
        "$p=0.0768$",
        "70.7\\% overall correctness",
        "84.7\\%",
        "88.0\\%",
        "$p=0.267$",
        "99 of those 108 writes",
        "single-annotator pilot, not a population prevalence",
    )
    missing = [fragment for fragment in required_fragments if fragment not in motivation]
    assert not missing, f"paper claim drift: {missing}"
    assert "\\input{sections/motivation}" in main_tex
    for suffix in ("pdf", "png"):
        figure = ROOT / "paper" / "fse2027" / "figures" / f"fig_motivation_evidence.{suffix}"
        assert figure.exists() and figure.stat().st_size > 10_000

    with (HERE / "per_episode.csv").open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 900
    assert len({(row["case_id"], row["arm"]) for row in rows}) == 900

    print("motivation paper audit: PASS")
    print("A=100 labeled / 40 structurally valid candidates; B/C=6x150 complete cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
