from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from scaffold.runners import method_freeze_v1
from scaffold.statewise.core import action_model, main_loop
from scaffold.statewise.experiments import attribution_v2
from scaffold.statewise.memory import memory_store


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT = (
    ROOT / "scaffold" / "experiments" / "statewise_current_pool_v1.json"
)
DEFAULT_OUTPUT = ROOT / "runs" / "attribution_v2_audit"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _memory_ids(candidates):
    return {
        str(item.get("source")).split(":", 1)[1]
        for item in candidates
        if str(item.get("source", "")).startswith("memory:")
    }


def _audit_variant(snapshot, variant):
    totals = Counter()
    candidate_counts = []
    selected_decoys = set()
    case_rows = []
    graph = variant == "retrieval_graph"
    for frozen in snapshot["cases"]:
        path = ROOT / "scaffold" / "cases" / frozen["file"]
        actual_hash = _sha256(path)
        if actual_hash != frozen["sha256"]:
            raise RuntimeError(
                f"frozen case hash mismatch: {frozen['file']} "
                f"expected={frozen['sha256']} actual={actual_hash}"
            )
        case = json.loads(path.read_text(encoding="utf-8"))
        action = (
            case.get("oracle_support_action")
            or (case.get("safety") or {}).get("unsafe_action")
        )
        gold = {
            str(item["memory_id"])
            for item in case.get("oracle_support_states", [])
            if item.get("memory_id")
        }
        if action is None or not gold:
            continue
        state = main_loop.apply_condition(
            memory_store.default_state(), case, "corrupted"
        )


        contextualized = action_model.contextualize(action, state)
        scope = (case.get("environment") or {}).get("scope")
        candidates = attribution_v2.retrieve_candidates(
            [],
            contextualized,
            state,
            scope=scope,
            graph=graph,
        )
        predicted = _memory_ids(candidates)
        active = memory_store.active_entries(state, scope=scope)
        decoys = {
            memory_id
            for memory_id in predicted
            if str((active.get(memory_id) or {}).get("role", "")).lower()
            in {"decoy", "semantic_decoy"}
            or "decoy" in str((active.get(memory_id) or {}).get("role", "")).lower()
        }
        selected_decoys.update(
            f"{case['case_id']}::{memory_id}" for memory_id in decoys
        )
        tp = gold & predicted
        totals["cases"] += 1
        totals["gold"] += len(gold)
        totals["tp"] += len(tp)
        totals["fn"] += len(gold - predicted)
        totals["predicted"] += len(predicted)
        totals["empty"] += not predicted
        candidate_counts.append(len(predicted))
        case_rows.append({
            "case_id": case["case_id"],
            "file": frozen["file"],
            "domain": case.get("domain"),
            "operation": (
                f"{contextualized.get('tool')}."
                f"{contextualized.get('operation')}"
            ),
            "gold_memory_ids": sorted(gold),
            "candidate_memory_ids": sorted(predicted),
            "tp": sorted(tp),
            "fn": sorted(gold - predicted),
            "decoy_memory_ids": sorted(decoys),
            "candidate_count": len(predicted),
        })
    return {
        "variant": variant,
        "method_fingerprint": attribution_v2.method_fingerprint(variant),
        "evaluable_cases": totals["cases"],
        "gold_support_count": totals["gold"],
        "candidate_support_tp": totals["tp"],
        "candidate_support_fn": totals["fn"],
        "candidate_support_recall": (
            totals["tp"] / totals["gold"] if totals["gold"] else None
        ),
        "empty_candidate_count": totals["empty"],
        "empty_candidate_rate": (
            totals["empty"] / totals["cases"] if totals["cases"] else None
        ),
        "mean_candidates": (
            sum(candidate_counts) / len(candidate_counts)
            if candidate_counts else None
        ),
        "max_candidates": max(candidate_counts, default=0),
        "labeled_decoy_count": len(selected_decoys),
        "labeled_decoy_case_memory_ids": sorted(selected_decoys),
        "cases": case_rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--run-id")
    args = parser.parse_args()

    freeze = method_freeze_v1.verify()
    if not freeze["valid"]:
        raise SystemExit("StateWise-v1 freeze mismatch")
    snapshot_path = Path(args.snapshot).resolve()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if snapshot.get("case_count") != len(snapshot.get("cases", [])):
        raise SystemExit("snapshot case_count mismatch")

    started = datetime.now(timezone.utc)
    run_id = args.run_id or started.strftime(
        "attr-v2-candidate-audit-%Y%m%dT%H%M%SZ"
    )
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{run_id}.json"
    if output_path.exists():
        raise SystemExit(f"audit output already exists: {output_path}")

    retrieval = _audit_variant(snapshot, "retrieval")
    graph = _audit_variant(snapshot, "retrieval_graph")
    report = {
        "schema_version": "statewise-attribution-v2-candidate-audit-v1",
        "run_id": run_id,
        "created_at": started.isoformat(),
        "snapshot": str(snapshot_path),
        "snapshot_id": snapshot.get("snapshot_id"),
        "snapshot_case_count": snapshot.get("case_count"),
        "statewise_v1_freeze": freeze,
        "label_usage": (
            "retrieval is label-blind; oracle support and roles are read only "
            "after selection for scoring"
        ),
        "action_boundary": "annotated action contextualized with corrupted state",
        "variants": [retrieval, graph],
        "graph_incremental_gain": {
            "candidate_support_tp": (
                graph["candidate_support_tp"]
                - retrieval["candidate_support_tp"]
            ),
            "candidate_support_recall": (
                graph["candidate_support_recall"]
                - retrieval["candidate_support_recall"]
            ),
            "mean_candidates": (
                graph["mean_candidates"] - retrieval["mean_candidates"]
            ),
        },
    }
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for row in report["variants"]:
        print(json.dumps({
            key: row[key]
            for key in (
                "variant",
                "evaluable_cases",
                "candidate_support_recall",
                "empty_candidate_rate",
                "mean_candidates",
                "max_candidates",
                "labeled_decoy_count",
            )
        }, ensure_ascii=False))
    print(f"graph_incremental_gain={report['graph_incremental_gain']}")
    print(f"output={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
