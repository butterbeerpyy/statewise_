import json
import sys
from pathlib import Path

from scaffold.statewise.evaluation import measurement


def _recovered_id(candidate):
    source = str(candidate.get("source") or "")
    if candidate.get("memory_id"):
        return candidate["memory_id"]
    return source.split(":", 1)[1] if source.startswith("memory:") else None


def _measure(ids, oracle_ids):
    true_positive = len(ids & oracle_ids)
    precision = true_positive / len(ids) if ids else (1.0 if not oracle_ids else 0.0)
    recall = true_positive / len(oracle_ids) if oracle_ids else 1.0
    return precision, recall


def recompute(case_dir):
    raw = json.loads((Path(case_dir) / "raw_result.json").read_text(encoding="utf-8"))
    metrics = raw.get("episode_attribution_metrics") or raw.get("attribution_metrics") or {}
    case_path = Path(case_dir) / "case_definition.json"
    case = json.loads(case_path.read_text(encoding="utf-8")) if case_path.exists() else {}
    oracle_ids = (
        measurement.annotated_memory_ids(case)
        if case else set(metrics.get("oracle_memory_ids_annotated") or metrics.get("oracle_memory_ids") or [])
    )


    candidate_ids, critical_ids = set(), set()
    for entry in raw.get("inspection_rounds") or []:
        if case:
            expected_action = case.get("oracle_support_action") or (case.get("safety") or {}).get("unsafe_action")
            aligned, _ = measurement.action_contract_aligned(entry.get("action"), expected_action)
            if not aligned:
                continue
        for candidate in entry.get("annotated_states") or []:
            recovered = _recovered_id(candidate)
            if not recovered:
                continue
            candidate_ids.add(recovered)
            if candidate.get("critical"):
                critical_ids.add(recovered)

    precision, recall = _measure(critical_ids, oracle_ids)
    return {
        "case_id": raw.get("case_id"),
        "oracle_memory_ids": sorted(oracle_ids),
        "reported_precision": metrics.get("precision"),
        "reported_recall": metrics.get("recall"),
        "recovered_candidate_ids": sorted(candidate_ids),
        "recovered_critical_ids": sorted(critical_ids),
        "recomputed_precision": round(precision, 4),
        "recomputed_recall": round(recall, 4),
    }


def main(argv):
    if len(argv) != 2:
        raise SystemExit("usage: recompute_attribution <exported_run_dir>")
    root = Path(argv[1])
    rows = []
    for case_dir in sorted(root.iterdir()):
        if case_dir.is_dir() and (case_dir / "raw_result.json").exists():
            rows.append(recompute(case_dir))

    if not rows:
        raise SystemExit(f"no exported cases with raw_result.json under {root}")

    for row in rows:
        print(f"{row['case_id']}")
        print(f"  oracle          : {row['oracle_memory_ids']}")
        print(f"  reported  P/R   : {row['reported_precision']} / {row['reported_recall']}")
        print(f"  recovered crit  : {row['recovered_critical_ids']}")
        print(f"  recomputed P/R  : {row['recomputed_precision']} / {row['recomputed_recall']}")


    scored = [row for row in rows if row["oracle_memory_ids"]]
    affected = [
        row for row in scored
        if row["reported_recall"] == 0 and row["recomputed_recall"] > 0
    ]
    print()
    print(f"cases_examined              : {len(rows)}")
    print(f"cases_with_oracle           : {len(scored)}")
    print(f"vacuous_empty_oracle        : {len(rows) - len(scored)} (excluded from means)")
    print(f"reported_zero_but_nonzero   : {len(affected)}")
    if scored:
        mean_reported = sum(row["reported_recall"] or 0 for row in scored) / len(scored)
        mean_recomputed = sum(row["recomputed_recall"] for row in scored) / len(scored)
        print(f"mean_recall reported        : {mean_reported:.4f}")
        print(f"mean_recall recomputed     : {mean_recomputed:.4f}")
    out = root / "recomputed_attribution.json"
    out.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"written                    : {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
