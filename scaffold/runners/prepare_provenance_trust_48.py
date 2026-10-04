from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FINAL_RUNTIME_ROOT = ROOT.parent / 'statewise'
BASE_CASES = (
    FINAL_RUNTIME_ROOT
    / "scaffold/experiments/w1_contract_corrected_v9/cases"
)
PRIMARY = (
    ROOT
    / 'paper_experiments/results/shared/permission_matched_v10_all_arms_20260819.xlsx'
)
OUTPUT = ROOT / "scaffold/experiments/provenance_trust_48_v1"
FULL_ARM = "statewise_v2_contract_corrected_typedfix"

ARMS = (
    FULL_ARM,
    "memlineage_trust",
    "corrupted",
    "rationale_approval",
)


TRUST = {
    "low": {
        "source": "agent_inference",
        "confidence": "low",
        "recent": False,
    },
    "high": {
        "source": "user_confirmed",
        "confidence": "high",
        "recent": True,
    },
    "untrusted": {
        "source": "external:web_search",
        "confidence": "low",
        "recent": False,
    },
}


CELLS = (
    ("LS", "low", "stale"),
    ("LC", "low", "correct"),
    ("HS", "high", "stale"),
    ("HC", "high", "correct"),
    ("US", "untrusted", "stale"),
)
PER_CELL = 12


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode()


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def _recent_timestamp(as_of: str) -> str:

    from datetime import datetime, timedelta

    parsed = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    return (parsed - timedelta(days=3)).isoformat()


def select_bases() -> list[dict[str, Any]]:

    import pandas as pd

    ep = pd.ExcelFile(PRIMARY).parse("Combined_Episodes")
    obj = ep.pivot_table(index="case_id", columns="arm",
                         values="behaviorally_correct")
    beh = ep.pivot_table(index="case_id", columns="arm",
                         values="expected_behavior", aggfunc="first")
    eligible = sorted(
        set(obj[(obj[FULL_ARM] == 1) & (obj["corrupted"] == 0)].index)
        & set(beh[beh[FULL_ARM] == "SHOULD_ACT"].index)
    )
    bases = []
    for case_id in eligible:
        path = BASE_CASES / f"{case_id}.json"
        if not path.is_file():
            continue
        case = json.loads(path.read_text(encoding="utf-8"))


        if (case.get("ground_truth_state") or {}).get("user_authoritative"):
            continue
        bases.append({"case_id": case_id, "case": case,
                      "sha256": _sha_path(path)})
    return bases


def select_paired_bases(bases: list[dict[str, Any]]) -> list[dict[str, Any]]:

    by_domain: dict[str, list[dict[str, Any]]] = {}
    for item in bases:
        by_domain.setdefault(item["case"]["domain"], []).append(item)
    for items in by_domain.values():
        items.sort(key=lambda entry: entry["case_id"])


    ordered: list[dict[str, Any]] = []
    domains = sorted(by_domain)
    while any(by_domain[domain] for domain in domains):
        for domain in domains:
            if by_domain[domain]:
                ordered.append(by_domain[domain].pop(0))

    if len(ordered) < PER_CELL:
        raise RuntimeError(
            f"need {PER_CELL} eligible bases, found {len(ordered)}"
        )
    return ordered[:PER_CELL]


def build_case(base: dict[str, Any], code: str, trust_key: str,
               truth: str) -> dict[str, Any]:
    case = copy.deepcopy(base["case"])
    original_id = case["case_id"]
    bundle = TRUST[trust_key]

    case["case_id"] = f"prov48_{code.lower()}_{original_id}"
    case["phase"] = "provenance_trust_48_v1"

    metadata = dict(case["state_metadata"])
    metadata["source"] = bundle["source"]
    metadata["confidence"] = bundle["confidence"]
    if bundle["recent"]:
        metadata["updated_at"] = _recent_timestamp(case["environment"]["as_of"])
    case["state_metadata"] = metadata

    correct_value = case["correct_state"]["value"]
    if truth == "correct":


        case["corrupted_state"] = {
            "value": correct_value,
            "text": case["correct_state"].get("text", ""),
        }
        case["corruption_operator"] = "NONE_RECORD_ALREADY_CORRECT"

    case["provenance_trust_cell"] = {
        "cell": code,
        "trust": trust_key,
        "ground_truth": truth,
        "source": bundle["source"],
        "confidence": bundle["confidence"],
        "recency": "recent" if bundle["recent"] else "frozen_original",
        "base_case_id": original_id,
        "base_case_sha256": base["sha256"],
        "manipulated_fields": (
            ["state_metadata.source", "state_metadata.confidence"]
            + (["state_metadata.updated_at"] if bundle["recent"] else [])
            + (["corrupted_state.value", "corrupted_state.text",
                "corruption_operator"] if truth == "correct" else [])
        ),
    }
    return case


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true",
                        help="write the package (default is a dry run)")
    args = parser.parse_args()

    sys.path.insert(0, str(FINAL_RUNTIME_ROOT))
    from scaffold.statewise.evaluation import case_schema

    bases = select_bases()
    print(f"eligible base cases : {len(bases)}")
    shared = select_paired_bases(bases)

    cases: list[dict[str, Any]] = []
    for code, trust_key, truth in CELLS:
        for base in shared:
            case = build_case(base, code, trust_key, truth)
            case_schema.assert_valid(case)
            cases.append(case)

    ids = [case["case_id"] for case in cases]
    if len(set(ids)) != len(ids):
        raise RuntimeError("duplicate generated case_id")
    print(f"shared base set     : {len(shared)} cases in every cell")
    print(f"generated cases     : {len(cases)}")
    by_cell: dict[str, int] = {}
    for case in cases:
        by_cell[case["provenance_trust_cell"]["cell"]] = by_cell.get(
            case["provenance_trust_cell"]["cell"], 0) + 1
    print(f"per cell            : {by_cell}")
    domains: dict[str, int] = {}
    for case in cases:
        domains[case["domain"]] = domains.get(case["domain"], 0) + 1
    print(f"domains             : {domains}")

    if not args.write:
        print("\ndry run: pass --write to materialize the package")
        return 0

    entries = []
    for case in cases:
        name = f"{case['case_id']}.json"
        _write(OUTPUT / "cases" / name, case)
        entries.append({
            "file": name,
            "case_id": case["case_id"],
            "domain": case["domain"],
            "cell": case["provenance_trust_cell"]["cell"],
            "sha256": _sha_path(OUTPUT / "cases" / name),
        })

    snapshot = {
        "schema_version": 1,
        "snapshot_id": "provenance_trust_48_v1",
        "purpose": (
            "Vary persistent-record provenance trust and ground truth "
            "independently, to test whether premise repair survives a stale "
            "record that the reliability model rates as trustworthy."
        ),
        "case_count": len(entries),
        "cells": {code: {"trust": t, "ground_truth": g}
                  for code, t, g in CELLS},
        "arms": list(ARMS),
        "base_snapshot": "w1_contract_corrected_v9",
        "cases": entries,
    }
    _write(OUTPUT / "snapshot.json", snapshot)

    design = {
        "reliability_model": (
            "source x confidence x scope x conflict x freshness "
            "(scaffold/statewise/core/reliability.py)"
        ),
        "continue_threshold": 0.6,
        "trust_bundles": TRUST,
        "expected_reliability": {
            "low": "~0.03-0.11 (frozen setting; router attempts resolution)",
            "high": "0.900 (router takes reliability-only CONTINUE)",
            "untrusted": "~0.03 (router resolves; MemLineage gate fires)",
        },
        "prereg_predictions": {
            "HS_vs_LS": (
                "StateWise objective correctness drops materially in HS, "
                "because route.py returns CONTINUE before resolution."
            ),
            "HC": (
                "Arms that survive HS by distrusting everything must pay in "
                "unnecessary questions or mutations here."
            ),
            "LC": "No arm should manufacture a repair when the record is correct.",
            "US": (
                "MemLineage refuses, demonstrating the gate is live; whether "
                "refusal also prevents task completion is the point of interest."
            ),
        },
        "not_pooled_with": "frozen 150-case headline matrix",
    }
    _write(OUTPUT / "design.json", design)


    original = json.loads(
        (FINAL_RUNTIME_ROOT
         / "scaffold/experiments"
         / "statewise_v2_contract_corrected_typedfix_freeze.json")
        .read_text(encoding="utf-8")
    )
    successor = copy.deepcopy(original)
    successor["version"] = (
        "StateWise-v2-contract-corrected-typedfix-provenance-trust48-v1"
    )
    successor["dataset"] = {
        "snapshot_id": "provenance_trust_48_v1",
        "snapshot_path":
            'scaffold/experiments/provenance_trust_48_v1/snapshot.json',
        "snapshot_sha256": _sha_path(OUTPUT / "snapshot.json"),
        "cases_root":
            'scaffold/experiments/provenance_trust_48_v1/cases',
        "case_count": len(entries),
    }
    for relative, expected in original.get("files", {}).items():
        actual = _sha_path(FINAL_RUNTIME_ROOT / relative)
        if actual != expected:
            raise RuntimeError(
                f"method file drifted, refusing to mint a successor freeze: "
                f"{relative}"
            )
    if successor.get("fingerprint") != original.get("fingerprint"):
        raise RuntimeError("successor freeze must not change the fingerprint")
    _write(OUTPUT / "typedfix_provenance_trust48_freeze.json", successor)
    _write(OUTPUT / "snapshot_fingerprint.json", {
        "snapshot_sha256": _sha_path(OUTPUT / "snapshot.json"),
        "cases_sha256": _sha_bytes(
            b"".join(sorted(
                (OUTPUT / "cases" / entry["file"]).read_bytes()
                for entry in entries
            ))
        ),
    })
    print(f"\nwrote package to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
