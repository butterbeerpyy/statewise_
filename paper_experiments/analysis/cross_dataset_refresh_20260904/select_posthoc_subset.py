from __future__ import annotations

import csv
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
TARGET_LOW = 20.0
TARGET_HIGH = 30.0
MIN_N = 10


def read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    candidates = []
    for path in sorted(HERE.glob("*_strata.csv")):
        if path.name in {"rq5_refresh_strata.csv", "cross_dataset_20_30pp_strata.csv"}:
            continue
        for row in read(path):
            if row.get("factor") not in {"domain", "operator", "domain_x_operator"}:
                continue
            n = int(row["n"])
            effect = float(row["difference_pp_statewise_minus_refresh"])
            if n >= MIN_N and TARGET_LOW <= effect <= TARGET_HIGH:
                candidates.append({
                    "dataset": row["dataset"],
                    "factor": row["factor"],
                    "value": row["value"],
                    "n": n,
                    "statewise_correct_n": int(row["statewise_correct_n"]),
                    "refresh_correct_n": int(row["refresh_correct_n"]),
                    "difference_pp": effect,
                    "ci95": [
                        float(row["paired_bootstrap_low_pp"]),
                        float(row["paired_bootstrap_high_pp"]),
                    ],
                    "mcnemar_exact_p": float(row["mcnemar_exact_p"]),
                })
    candidates.sort(key=lambda row: (-row["n"], -row["difference_pp"]))
    if not candidates:
        raise RuntimeError("no eligible outcome-selected subset")
    selected = candidates[0]

    replications = [
        {
            "dataset": row["dataset"],
            "n": int(row["n"]),
            "statewise_correct_n": int(row["statewise_correct_n"]),
            "refresh_correct_n": int(row["refresh_correct_n"]),
            "difference_pp": float(row["difference_pp_statewise_minus_refresh"]),
            "ci95": [
                float(row["paired_bootstrap_low_pp"]),
                float(row["paired_bootstrap_high_pp"]),
            ],
        }
        for row in read(HERE / "cross_dataset_feature_replication.csv")
        if row["feature"] == "Git state"
    ]
    payload = {
        "schema_version": "posthoc-outcome-selected-subset-v1",
        "selection_timing": "after all compared outcomes were available",
        "selection_rule": (
            "Among predeclared dataset/domain/operator/domain-by-operator rows "
            "with n>=10 and observed StateWise-minus-Refresh effect in [20,30] pp, "
            "choose the largest n, breaking ties by larger observed effect."
        ),
        "selected": selected,
        "all_eligible_candidates": candidates,
        "same_feature_other_datasets": replications,
        "inference_status": (
            "exploratory and selection-biased; cannot be used for confirmatory "
            "p-values or a general superiority claim"
        ),
    }
    (HERE / "posthoc_selected_subset.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Outcome-selected exploratory subset",
        "",
        payload["selection_rule"],
        "",
        f"Selected: `{selected['dataset']} / {selected['factor']}={selected['value']}`; "
        f"n={selected['n']}, StateWise {selected['statewise_correct_n']}, "
        f"Refresh {selected['refresh_correct_n']}, difference {selected['difference_pp']:+.1f} pp.",
        "",
        "This subset was chosen after outcomes were known. Its interval and p-value are descriptive only.",
        "",
        "## Same Git-state feature elsewhere",
        "",
        "| Dataset | n | StateWise | Refresh | Difference |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in replications:
        lines.append(
            f"| {row['dataset']} | {row['n']} | {row['statewise_correct_n']} | "
            f"{row['refresh_correct_n']} | {row['difference_pp']:+.1f} pp |"
        )
    (HERE / "POSTHOC_SELECTED_SUBSET.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
