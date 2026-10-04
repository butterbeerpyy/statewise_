from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
EVAL = REPO / "paper/fse2027/sections/evaluation.tex"
LIMITS = REPO / "paper/fse2027/sections/limitations.tex"
MAIN = REPO / "paper/fse2027/main.tex"
RUN = Path('runs/provenance-trust48-gpt56sol-20260828-r1')
PKG = REPO / "scaffold/experiments/provenance_trust_48_v1"
FULL = "statewise_v2_contract_corrected_typedfix"

fails: list[str] = []
n = 0


def want(label: str, needle: str, text: str) -> None:
    global n
    n += 1
    if needle not in text:
        fails.append("%-46s missing: %s" % (label, needle))


def rows(name: str) -> list[dict[str, str]]:
    with (HERE / name).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    global n
    ev = EVAL.read_text(encoding="utf-8")
    lim = LIMITS.read_text(encoding="utf-8")
    main_tex = MAIN.read_text(encoding="utf-8")

    obj = {r["method"]: r for r in rows("cell_objective.csv")}
    viol = {r["method"]: r for r in rows("cell_violation.csv")}
    paired = rows("paired_contrasts.csv")


    for method, row in obj.items():
        for cell in ("LS", "LC", "HS", "HC", "US"):
            want("obj %s/%s" % (method, cell), row[cell], ev)
    for method, row in viol.items():
        for cell in ("LS", "LC", "HS", "HC", "US"):
            want("viol %s/%s" % (method, cell), row[cell], ev)


    hs_ls = next(r for r in paired
                 if r["method"] == "StateWise" and r["contrast"] == "HS - LS")
    want("HS-LS diff", hs_ls["difference"].lstrip("-"), ev)
    want("HS-LS CI", "[%s,%s]" % (hs_ls["ci_low"], hs_ls["ci_high"]), ev)
    hs_hc = next(r for r in paired
                 if r["method"] == "StateWise" and r["contrast"] == "HS - HC")
    want("HS-HC diff", hs_hc["difference"].lstrip("-"), ev)


    want("HS-LS p", "9.77", ev)
    want("HS-HC p", "4.88", ev)
    for label, row in (("HS-LS", hs_ls), ("HS-HC", hs_hc)):
        p = float(row["mcnemar_p"])
        mant = float(("%.2e" % p).split("e")[0])
        if abs(mant - (9.77 if label == "HS-LS" else 4.88)) > 0.01:
            fails.append("%s p-value mantissa is %.2f, paper says otherwise"
                         % (label, mant))
        n += 1


    rec = pd.DataFrame(json.loads(
        (RUN / "pilot_summary.json").read_text(encoding="utf-8"))["records"])
    meta = {}
    for entry in json.loads(
        (PKG / "snapshot.json").read_text(encoding="utf-8")
    )["cases"]:
        case = json.loads(
            (PKG / "cases" / entry["file"]).read_text(encoding="utf-8"))
        meta[case["case_id"]] = (
            case["provenance_trust_cell"]["cell"], case["domain"])
    rec["cell"] = rec.case_id.map(lambda c: meta[c][0])
    rec["domain"] = rec.case_id.map(lambda c: meta[c][1])
    sw = rec[rec.arm == FULL]


    for cell, expect in (("LS", 1.0), ("LC", 1.0), ("US", 1.0),
                         ("HS", 0.0), ("HC", 0.0)):
        got = sw[sw.cell == cell].repair_performed.mean()
        n += 1
        if abs(got - expect) > 1e-9:
            fails.append("repair_performed %s is %.2f, paper implies %.2f"
                         % (cell, got, expect))


    hs = sw[sw.cell == "HS"]
    env = hs[hs.domain == "environment_state"]
    git = hs[hs.domain == "git_state"]
    n += 2
    if not (len(env) == 6 and env.safety_violation.sum() == 6):
        fails.append("environment HS violations: %d/%d, paper says 6 of 6"
                     % (env.safety_violation.sum(), len(env)))
    if not (len(git) == 6 and git.safety_violation.sum() == 0):
        fails.append("git HS violations: %d/%d, paper says 0 of 6"
                     % (git.safety_violation.sum(), len(git)))
    want("env 6 of 6", "(6 of 6)", ev)
    want("git 0 of 6", "(0 of 6)", ev)


    ml = rec[rec.arm == "memlineage_trust"]
    us = ml[ml.cell == "US"]
    n += 1
    if not (len(us) == 12 and us.lineage_blocked.sum() == 12):
        fails.append("MemLineage US blocked %d/%d, paper says all 12"
                     % (us.lineage_blocked.sum(), len(us)))
    want("memlineage blocks 12", "all 12 episodes", ev)


    bad = rec[rec.status.isin(["FAILED", "ERROR"])]
    n += 1
    if len(bad):
        fails.append("run has %d failed episodes; paper claims none" % len(bad))
    want("episode count", "240 episodes", ev)
    want("no attrition", "no attrition", ev)


    want("low reliability range", "0.03--0.11", ev)
    want("threshold", "0.60", ev)
    want("high reliability", "0.900", ev)
    want("table trust 0.026", "0.026", ev)


    want("abstract qualified", "correctness falls to 0.0", main_tex)
    want("conclusion qualified", "never checked", main_tex)
    want("limitations updated", "91.7\\% to 0.0\\%", lim)

    print("=" * 72)
    print("PROVENANCE VERIFY: %d checks, %d failures" % (n, len(fails)))
    print("=" * 72)
    if fails:
        for item in fails:
            print("  FAIL  " + item)
        return 1
    print("  paper matches the run and the CSVs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
