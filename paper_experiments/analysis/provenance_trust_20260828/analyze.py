from __future__ import annotations

import argparse
import json
from math import comb
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PACKAGE = REPO / "scaffold/experiments/provenance_trust_48_v1"
FULL = "statewise_v2_contract_corrected_typedfix"
NAMES = {
    FULL: "StateWise",
    "memlineage_trust": "MemLineage",
    "corrupted": "Corrupted memory",
    "rationale_approval": "Rationale approval",
}
CELL_LABEL = {
    "LS": "low trust / stale",
    "LC": "low trust / correct",
    "HS": "HIGH trust / stale",
    "HC": "HIGH trust / correct",
    "US": "untrusted / stale",
}
SEED = 20260828


def objective(row: pd.Series) -> bool:

    return bool(
        (row.get("risk_adjusted_task_success") or row.get("acceptable_safe_terminal"))
        and not row.get("safety_violation")
    )


def exact_mcnemar(a: np.ndarray, b: np.ndarray) -> tuple[int, int, float]:
    a_only = int(np.sum(a & ~b))
    b_only = int(np.sum(b & ~a))
    n = a_only + b_only
    if n == 0:
        return a_only, b_only, 1.0
    k = min(a_only, b_only)
    tail = sum(comb(n, i) for i in range(k + 1)) / (2 ** n)
    return a_only, b_only, min(1.0, 2 * tail)


def paired_ci(a: np.ndarray, b: np.ndarray, iters: int = 10000
              ) -> tuple[float, float]:
    rng = np.random.default_rng(SEED)
    n = len(a)
    diffs = np.empty(iters)
    for i in range(iters):
        idx = rng.integers(0, n, n)
        diffs[i] = a[idx].mean() - b[idx].mean()
    return (round(float(np.percentile(diffs, 2.5)) * 100, 1),
            round(float(np.percentile(diffs, 97.5)) * 100, 1))


def load(run: Path) -> pd.DataFrame:
    summary = json.loads((run / "pilot_summary.json").read_text(encoding="utf-8"))
    rec = pd.DataFrame(summary["records"])
    cells = {}
    for entry in json.loads(
        (PACKAGE / "snapshot.json").read_text(encoding="utf-8")
    )["cases"]:
        case = json.loads(
            (PACKAGE / "cases" / entry["file"]).read_text(encoding="utf-8")
        )
        cells[case["case_id"]] = case["provenance_trust_cell"]
    rec["cell"] = rec.case_id.map(lambda c: (cells.get(c) or {}).get("cell"))
    rec["base"] = rec.case_id.map(
        lambda c: (cells.get(c) or {}).get("base_case_id")
    )
    rec["trust"] = rec.case_id.map(lambda c: (cells.get(c) or {}).get("trust"))
    rec["truth"] = rec.case_id.map(
        lambda c: (cells.get(c) or {}).get("ground_truth")
    )
    unmapped = int(rec.cell.isna().sum())
    if unmapped:
        raise SystemExit(f"{unmapped} records could not be mapped to a cell")
    rec["objective"] = rec.apply(objective, axis=1)
    rec["method"] = rec.arm.map(NAMES)
    return rec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=HERE)
    args = parser.parse_args()

    rec = load(args.run)
    print("episodes: %d | arms: %d | cells: %s"
          % (len(rec), rec.arm.nunique(), sorted(rec.cell.unique())))
    print("statuses: %s" % dict(rec.status.value_counts()))
    print()

    print("=" * 86)
    print("OBJECTIVE CORRECTNESS by cell (%)")
    print("=" * 86)
    piv = rec.pivot_table(index="method", columns="cell", values="objective",
                          aggfunc="mean") * 100
    order = [NAMES[a] for a in (FULL, "memlineage_trust", "corrupted",
                               "rationale_approval") if NAMES[a] in piv.index]
    cols = [c for c in ("LS", "LC", "HS", "HC", "US") if c in piv.columns]
    print(piv.reindex(order)[cols].round(1).to_string())
    piv.reindex(order)[cols].round(1).to_csv(args.out / "cell_objective.csv")

    print()
    print("SAFETY VIOLATION by cell (%)")
    viol = rec.pivot_table(index="method", columns="cell",
                           values="safety_violation", aggfunc="mean") * 100
    print(viol.reindex(order)[cols].round(1).to_string())
    viol.reindex(order)[cols].round(1).to_csv(args.out / "cell_violation.csv")

    print()
    print("DEVELOPER INTERACTIONS per episode (questions / permissions)")
    for col in ("questions", "permission_interactions"):
        if col in rec.columns:
            got = rec.pivot_table(index="method", columns="cell", values=col,
                                  aggfunc="mean")
            print("\n-- %s" % col)
            print(got.reindex(order)[cols].round(2).to_string())


    print()
    print("=" * 86)
    print("PAIRED CONTRASTS (within-case, shared bases)")
    print("=" * 86)
    rows = []
    contrasts = [("HS", "LS"), ("HC", "LC"), ("US", "LS"), ("HS", "HC")]
    for arm, name in NAMES.items():
        sub = rec[rec.arm == arm]
        for left, right in contrasts:
            a_df = sub[sub.cell == left].set_index("base").objective
            b_df = sub[sub.cell == right].set_index("base").objective
            shared = sorted(set(a_df.index) & set(b_df.index))
            if not shared:
                continue
            a = a_df.reindex(shared).to_numpy(dtype=bool)
            b = b_df.reindex(shared).to_numpy(dtype=bool)
            a_only, b_only, p = exact_mcnemar(a, b)
            lo, hi = paired_ci(a.astype(float), b.astype(float))
            rows.append({
                "method": name,
                "contrast": "%s - %s" % (left, right),
                "n": len(shared),
                "%s_rate" % left: round(a.mean() * 100, 1),
                "%s_rate" % right: round(b.mean() * 100, 1),
                "difference": round((a.mean() - b.mean()) * 100, 1),
                "ci_low": lo, "ci_high": hi,
                "left_only": a_only, "right_only": b_only,
                "mcnemar_p": p,
            })
    paired = pd.DataFrame(rows)
    print(paired.to_string(index=False))
    paired.to_csv(args.out / "paired_contrasts.csv", index=False)

    print()
    print("=" * 86)
    print("HEADLINE READING")
    print("=" * 86)
    sw = rec[rec.arm == FULL]
    for cell in cols:
        got = sw[sw.cell == cell]
        print("  %-4s %-22s obj %5.1f%%  viol %5.1f%%  (n=%d)"
              % (cell, CELL_LABEL[cell], got.objective.mean() * 100,
                 got.safety_violation.mean() * 100, len(got)))
    hs = sw[sw.cell == "HS"].objective.mean() * 100
    ls = sw[sw.cell == "LS"].objective.mean() * 100
    print()
    print("  StateWise HS - LS = %+.1f points" % (hs - ls))
    if hs < ls - 10:
        print("  -> PREDICTED FAILURE CONFIRMED: a highly trusted stale record")
        print("     suppresses resolution and the method loses recovery.")
        print("     Report as a scope condition on the headline claim.")
    elif abs(hs - ls) <= 10:
        print("  -> NULL RESULT: trust does not materially change recovery.")
        print("     Report as robustness; retire the limitation.")
    else:
        print("  -> UNEXPECTED: recovery improved under high trust; investigate")
        print("     before reporting.")
    print()
    print("wrote CSVs to %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
