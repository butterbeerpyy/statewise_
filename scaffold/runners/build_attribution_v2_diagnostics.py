from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from scaffold.runners.analyze_attribution_v2_compare import (
    CASES_ROOT,
    _action_contract_alignment,
)


ROOT = Path(__file__).resolve().parents[2]


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _ids(value):
    return sorted(set(value or []))


def _record_view(record, case):
    raw = record.get("raw_result") or {}
    summary = record.get("summary") or {}
    api = record.get("api") or {}
    metrics = raw.get("episode_attribution_metrics") or raw.get("attribution_metrics") or {}
    gold = set(metrics.get("oracle_memory_ids_annotated") or metrics.get("oracle_memory_ids") or [])
    candidate = set((metrics.get("candidate") or {}).get("memory_ids") or [])
    prefilter = set((metrics.get("prefilter") or {}).get("memory_ids") or [])
    final = set((metrics.get('final') or {}).get("memory_ids") or [])
    annotated = {
        item.get("memory_id"): item
        for item in (raw.get("annotated_states") or [])
        if item.get("memory_id")
    }
    probed = {
        memory_id
        for memory_id, item in annotated.items()
        if item.get("counterfactual_tested")
    }
    stability = {
        memory_id: {
            "stability": item.get("counterfactual_stability"),
            "delta_cf": item.get("delta_cf"),
            "critical": item.get("critical"),
            "critical_basis": item.get("critical_basis"),
            "filter_reason": item.get("filter_reason"),
            "candidate_origin": item.get("candidate_origin"),
            "retrieval_score": item.get("candidate_retrieval_score"),
            "p_prov": item.get("p_prov"),
            "p_ground": item.get("p_ground"),
        }
        for memory_id, item in annotated.items()
    }
    aligned, alignment_reason = _action_contract_alignment(record)
    annotated_action = case.get("oracle_support_action") or (
        case.get("safety") or {}
    ).get("unsafe_action")
    questions = raw.get("questions_asked") or []
    state = {
        case.get("memory_id"): case.get("memory_key"),
        **{
            item.get("id"): item.get("key")
            for item in case.get("context_memories", [])
            if isinstance(item, dict)
        },
    }
    gold_keys = {state.get(memory_id) for memory_id in gold}
    wrong_questions = sum(
        question.get("state_key") not in gold_keys
        for question in questions
        if isinstance(question, dict)
    )
    mutation = summary.get("unnecessary_mutation") or {}
    return {
        "candidate": candidate,
        "prefilter": prefilter,
        "probed": probed,
        'final': final,
        "gold": gold,
        "stability": stability,
        "actual_action": raw.get("initial_action"),
        "annotated_action": annotated_action,
        "aligned": aligned,
        "alignment_reason": alignment_reason,
        "tp": final & gold,
        "fp": final - gold,
        "fn": gold - final,
        "task_success": bool(summary.get("task_success")),
        "safety_violation": bool(summary.get("safety_violation")),
        "calls": int(api.get("calls") or 0),
        "tokens": int(api.get("total_tokens") or 0),
        "latency": float(api.get("latency_seconds") or 0.0),
        "steps": int(summary.get("steps") or 0),
        "questions": len(questions),
        "wrong_questions": wrong_questions,
        "unnecessary_mutations": int(
            mutation.get("unnecessary_mutation_count") or 0
        ),
    }


def _failures(view, case):
    failures = []
    if not view["aligned"]:
        failures.append((
            "C",
            "action-contract mismatch",
            view["alignment_reason"],
        ))
    missing_candidates = view["gold"] - view["candidate"]
    if missing_candidates:
        failures.append((
            "A",
            "candidate coverage failure",
            f"gold not proposed: {','.join(sorted(missing_candidates))}",
        ))
    missed_probe = (view["gold"] & view["candidate"]) - view["probed"]
    if missed_probe:
        failures.append((
            "B",
            "candidate ranking / probe-budget failure",
            f"candidate not probed: {','.join(sorted(missed_probe))}",
        ))
    if view["fp"]:
        failures.append((
            "B",
            "candidate ranking / probe-budget failure",
            f"unsupported candidates survived: {','.join(sorted(view['fp']))}",
        ))
    unstable = []
    threshold_filtered = []
    for memory_id in view["fn"] & view["probed"]:
        item = view["stability"].get(memory_id, {})
        stability = float(item.get("stability") or 0.0)
        delta = float(item.get("delta_cf") or 0.0)
        if stability < 0.50 or delta < 0.50:
            unstable.append(memory_id)
        else:
            threshold_filtered.append(memory_id)
    if unstable:
        failures.append((
            "D",
            "counterfactual instability",
            f"probed support unstable/low-delta: {','.join(sorted(unstable))}",
        ))
    if threshold_filtered:
        failures.append((
            "E",
            "final threshold/filter failure",
            f"robust support removed at final filter: "
            f"{','.join(sorted(threshold_filtered))}",
        ))
    expected_task_success = bool(
        (((case.get("expected") or {}).get("corrupted") or {}).get("episode") or {})
        .get("task_success")
    )
    if expected_task_success and not view["task_success"]:
        failures.append((
            "F",
            "planner/runtime failure unrelated to Attribution",
            "case expects completion but episode did not complete",
        ))
    if not failures:
        failures.append(("PASS", "no diagnosed failure", ""))
    return failures


def build(manifest_paths, merge_latest_by_case=False):
    paired = {}
    taxonomy = []
    provider_failures = {}
    run_ids = []
    for path in manifest_paths:
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
        run_ids.append(manifest.get("run_id"))
        for record in manifest.get("records", []):
            failure_key = (
                record.get("case_id"),
                int(record.get("trial") or 0),
                record.get("variant"),
            )
            if record.get("status") != "SUCCEEDED":
                provider_failures[failure_key] = {
                    "run_id": manifest.get("run_id"),
                    "case_id": record.get("case_id"),
                    "trial": int(record.get("trial") or 0),
                    "variant": record.get("variant"),
                    "failure_code": "G",
                    "failure_type": "measurement/provider failure",
                    "failure_detail": (
                        f"{record.get('error_type')}: "
                        f"{str(record.get('error') or '')[:300]}"
                    ),
                    "action_contract_aligned": "",
                    "task_success": "",
                    "safety_violation": "",
                    "provider_calls": int(
                        (record.get("api") or {}).get("calls") or 0
                    ),
                }
                continue
            provider_failures.pop(failure_key, None)
            case_path = CASES_ROOT / f"{record['case_id']}.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            key = (
                (
                    "merged"
                    if merge_latest_by_case
                    else manifest.get("run_id")
                ),
                record["case_id"],
                int(record.get("trial") or 0),
            )
            view = _record_view(record, case)
            view["source_run_id"] = manifest.get("run_id")
            paired.setdefault(key, {
                "run_id": key[0],
                "case_id": record["case_id"],
                "trial": int(record.get("trial") or 0),
                "gold_support_ids": _json(_ids(view["gold"])),
                "actual_initial_action": _json(view["actual_action"]),
                "annotated_action_contract": _json(view["annotated_action"]),
                "action_contract_aligned": view["aligned"],
                "action_alignment_reason": view["alignment_reason"],
            })[record["variant"]] = view


    for base in paired.values():
        case = json.loads(
            (CASES_ROOT / f"{base['case_id']}.json").read_text(encoding="utf-8")
        )
        for variant in ("v1", "retrieval"):
            view = base.get(variant)
            if not view:
                continue
            for code, name, detail in _failures(view, case):
                taxonomy.append({
                    "run_id": view["source_run_id"],
                    "case_id": base["case_id"],
                    "trial": base["trial"],
                    "variant": variant,
                    "failure_code": code,
                    "failure_type": name,
                    "failure_detail": detail,
                    "action_contract_aligned": view["aligned"],
                    "task_success": view["task_success"],
                    "safety_violation": view["safety_violation"],
                    "provider_calls": view["calls"],
                })
    taxonomy.extend(provider_failures.values())

    rows = []
    variants = ("v1", "retrieval")
    fields = (
        "candidate_ids",
        "prefilter_ids",
        "counterfactual_probed_ids",
        "counterfactual_stability",
        "final_attributed_ids",
        "tp_ids",
        "fp_ids",
        "fn_ids",
        "task_success",
        "safety_violation",
        "provider_calls",
        "tokens",
        "latency_seconds",
        "steps",
        "questions",
        "wrong_questions",
        "unnecessary_mutations",
        "failure_stage",
        "source_run_id",
    )
    for key in sorted(paired):
        base = paired[key]
        row = {
            name: value
            for name, value in base.items()
            if name not in variants
        }
        for variant in variants:
            view = base.get(variant)
            if not view:
                for field in fields:
                    row[f"{variant}_{field}"] = ""
                continue
            failures = _failures(
                view,
                json.loads(
                    (CASES_ROOT / f"{base['case_id']}.json").read_text(
                        encoding="utf-8"
                    )
                ),
            )
            values = {
                "candidate_ids": _json(_ids(view["candidate"])),
                "prefilter_ids": _json(_ids(view["prefilter"])),
                "counterfactual_probed_ids": _json(_ids(view["probed"])),
                "counterfactual_stability": _json(view["stability"]),
                "final_attributed_ids": _json(_ids(view['final'])),
                "tp_ids": _json(_ids(view["tp"])),
                "fp_ids": _json(_ids(view["fp"])),
                "fn_ids": _json(_ids(view["fn"])),
                "task_success": view["task_success"],
                "safety_violation": view["safety_violation"],
                "provider_calls": view["calls"],
                "tokens": view["tokens"],
                "latency_seconds": round(view["latency"], 4),
                "steps": view["steps"],
                "questions": view["questions"],
                "wrong_questions": view["wrong_questions"],
                "unnecessary_mutations": view["unnecessary_mutations"],
                "failure_stage": "|".join(
                    code for code, _, _ in failures if code != "PASS"
                ) or "PASS",
                "source_run_id": view["source_run_id"],
            }
            row.update({
                f"{variant}_{field}": values[field]
                for field in fields
            })
        rows.append(row)
    return rows, taxonomy, run_ids


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", nargs="+")
    parser.add_argument(
        "--diagnostic-output",
        default=str(ROOT / "attribution_v2_diagnostic.csv"),
    )
    parser.add_argument(
        "--taxonomy-output",
        default=str(ROOT / "attribution_v2_failure_taxonomy.csv"),
    )
    parser.add_argument(
        "--merge-latest-by-case",
        action="store_true",
        help=(
            "pair case/trial across manifests and let later successful records "
            "supersede earlier records of the same variant"
        ),
    )
    args = parser.parse_args()
    rows, taxonomy, run_ids = build(
        args.manifest,
        merge_latest_by_case=args.merge_latest_by_case,
    )
    diagnostic = Path(args.diagnostic_output).resolve()
    failures = Path(args.taxonomy_output).resolve()
    _write_csv(diagnostic, rows)
    _write_csv(failures, taxonomy)
    print(json.dumps({
        "run_ids": run_ids,
        "diagnostic": str(diagnostic),
        "diagnostic_rows": len(rows),
        "taxonomy": str(failures),
        "taxonomy_rows": len(taxonomy),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
