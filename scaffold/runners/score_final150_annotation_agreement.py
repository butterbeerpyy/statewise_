from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scaffold.statewise.evaluation import measurement


def _rows(path: Path) -> dict[str, dict]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return {row["item_id"]: row for row in csv.DictReader(handle)}


def _ids(value: str) -> set[str]:

    items = {item.strip() for item in (value or "").split(";") if item.strip()}
    return set() if items == {"NO_SUPPORT"} else items - {"NO_SUPPORT"}


def _parse_json(value: str):
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value.strip() if isinstance(value, str) else value


def _normalized_text(value: str) -> str:
    return " ".join((value or "").split()).casefold()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _semantic_category_pairs(left: list, right: list) -> list[tuple[str, str]]:

    representatives = []

    def category(value) -> str:
        for index, representative in enumerate(representatives):
            if measurement.semantic_equal(value, representative):
                return f"c{index}"
        representatives.append(value)
        return f"c{len(representatives) - 1}"

    return [(category(a), category(b)) for a, b in zip(left, right)]


def _kappa(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    observed = sum(a == b for a, b in pairs) / len(pairs)
    a_counts, b_counts = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    labels = set(a_counts) | set(b_counts)
    expected = sum(
        (a_counts[label] / len(pairs)) * (b_counts[label] / len(pairs))
        for label in labels
    )
    return 1.0 if expected == 1.0 and observed == 1.0 else (
        (observed - expected) / (1.0 - expected) if expected < 1.0 else None
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    base = Path('paper_experiments/results/shared/annotation_b_v9')
    parser.add_argument("--annotation-b", type=Path, default=base / "ANNOTATOR_B_BLINDED.csv")
    parser.add_argument("--private-key", type=Path, default=base / "ANNOTATION_A_PRIVATE_KEY.csv")
    parser.add_argument("--output", type=Path, default=base / "agreement_report.json")
    parser.add_argument("--disagreements", type=Path, default=base / "agreement_disagreements.csv")
    args = parser.parse_args()
    b, a = _rows(args.annotation_b), _rows(args.private_key)
    if set(a) != set(b):
        raise ValueError("annotation A/B item IDs differ")
    case_mismatches = [item for item in a if a[item]["case_id"] != b[item]["case_id"]]
    if case_mismatches:
        raise ValueError(f"annotation A/B case IDs differ: {case_mismatches[:10]}")
    required = (
        "b_expected_behavior_SHOULD_ACT_or_SHOULD_STOP",
        "b_support_memory_ids_semicolon_separated",
        "b_correct_state_value_json",
        "b_safety_invariant",
    )
    incomplete = [item_id for item_id, row in b.items() if any(
        not str(row.get(field) or "").strip() for field in required
    )]
    report = {
        "items": len(a),
        "completed_items": len(a) - len(incomplete),
        "incomplete_items": len(incomplete),
        "status": "NOT_COMPUTABLE" if incomplete else "COMPLETE",
        "agreement": None,
        "incomplete_item_examples": incomplete[:20],
        "input_sha256": {
            "annotation_b": _sha256(args.annotation_b),
            "private_key": _sha256(args.private_key),
        },
    }
    if not incomplete:
        invalid_behavior = [item for item in b if
            b[item]["b_expected_behavior_SHOULD_ACT_or_SHOULD_STOP"].strip().upper()
            not in {"SHOULD_ACT", "SHOULD_STOP"}
        ]
        if invalid_behavior:
            raise ValueError(f"invalid behavior labels: {invalid_behavior[:10]}")
        behavior = [
            (a[item]["a_expected_behavior"].strip().upper(),
             b[item]["b_expected_behavior_SHOULD_ACT_or_SHOULD_STOP"].strip().upper())
            for item in sorted(a)
        ]
        support_scores, support_categories = [], []
        state_left, state_right, state_equal, safety_pairs = [], [], [], []
        disagreement_rows = []
        for item in sorted(a):
            left, right = _ids(a[item]["a_support_memory_ids"]), _ids(
                b[item]["b_support_memory_ids_semicolon_separated"]
            )
            support_score = 1.0 if left == right else (
                len(left & right) / len(left | right) if left | right else 1.0
            )
            support_scores.append(support_score)
            support_categories.append((";".join(sorted(left)), ";".join(sorted(right))))
            parsed_left = _parse_json(a[item]["a_correct_state_value_json"])
            parsed_right = _parse_json(b[item]["b_correct_state_value_json"])
            state_left.append(parsed_left)
            state_right.append(parsed_right)
            state_match = measurement.semantic_equal(parsed_left, parsed_right)
            state_equal.append(state_match)
            safety_left = _normalized_text(a[item]["a_safety_invariant"])
            safety_right = _normalized_text(b[item]["b_safety_invariant"])
            safety_pairs.append((safety_left, safety_right))
            behavior_match = behavior[len(support_scores) - 1][0] == behavior[len(support_scores) - 1][1]
            safety_match = safety_left == safety_right
            if not (behavior_match and support_score == 1.0 and state_match and safety_match):
                disagreement_rows.append({
                    "item_id": item,
                    "case_id": a[item]["case_id"],
                    "behavior_match": behavior_match,
                    "behavior_a": behavior[len(support_scores) - 1][0],
                    "behavior_b": behavior[len(support_scores) - 1][1],
                    "support_exact": support_score == 1.0,
                    "support_jaccard": support_score,
                    "support_a": ";".join(sorted(left)),
                    "support_b": ";".join(sorted(right)),
                    "correct_state_match": state_match,
                    "correct_state_a": a[item]["a_correct_state_value_json"],
                    "correct_state_b": b[item]["b_correct_state_value_json"],
                    "safety_invariant_match": safety_match,
                    "safety_invariant_a": a[item]["a_safety_invariant"],
                    "safety_invariant_b": b[item]["b_safety_invariant"],
                })
        state_pairs = _semantic_category_pairs(state_left, state_right)


        scored_disagreements = [
            row for row in disagreement_rows
            if not (row["behavior_match"] and row["support_exact"]
                    and row["correct_state_match"])
        ]
        report["agreement"] = {
            "behavior_exact_rate": sum(x == y for x, y in behavior) / len(behavior),
            "behavior_cohen_kappa": _kappa(behavior),
            "support_set_mean_jaccard": sum(support_scores) / len(support_scores),
            "support_set_exact_rate": sum(x == 1.0 for x in support_scores) / len(support_scores),
            "support_set_cohen_kappa": _kappa(support_categories),
            "correct_state_semantic_exact_rate": sum(state_equal) / len(state_equal),
            "correct_state_cohen_kappa": _kappa(state_pairs),
            "scored_field_disagreement_items": len(scored_disagreements),
            "scored_fields": ["expected_behavior", "support_set", "correct_state_value"],
            "safety_invariant_lexical_exact_rate": (
                sum(x == y for x, y in safety_pairs) / len(safety_pairs)
            ),
            "safety_invariant_note": (
                "Free-text field compared by normalized string equality, which measures "
                "phrasing rather than substantive agreement; it is a diagnostic only and "
                "is excluded from scored_field_disagreement_items. Semantic scoring of "
                "this field would require adjudication we have not performed."
            ),
            "kappa_note": (
                "Behavior kappa is the primary categorical reliability statistic. "
                "Support-set and state-value kappas are reported for completeness but "
                "have sparse/high-cardinality label spaces; read them with their exact "
                "agreement and Jaccard rates."
            ),
        }
        args.disagreements.parent.mkdir(parents=True, exist_ok=True)
        fields = list(disagreement_rows[0]) if disagreement_rows else [
            "item_id", "case_id", "behavior_match", "behavior_a", "behavior_b",
            "support_exact", "support_jaccard", "support_a", "support_b",
            "correct_state_match", "correct_state_a", "correct_state_b",
            "safety_invariant_match", "safety_invariant_a", "safety_invariant_b",
        ]
        with args.disagreements.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(disagreement_rows)
        report["disagreements_csv"] = str(args.disagreements)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not incomplete else 2


if __name__ == "__main__":
    raise SystemExit(main())
