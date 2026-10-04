import json
import sys
from pathlib import Path

from scaffold.statewise.evaluation import measurement


def diagnose(case_dir):
    path = Path(case_dir)
    raw = json.loads((path / "raw_result.json").read_text(encoding="utf-8"))
    case_path = path / "case_definition.json"
    case = json.loads(case_path.read_text(encoding="utf-8")) if case_path.exists() else {}
    metrics = raw.get("episode_attribution_metrics") or (
        measurement.aggregate_episode_attribution(
            case, raw.get("inspection_rounds") or []
        ) if case else raw.get("attribution_metrics") or {}
    )

    print(f"=== {path.name}")
    print(f"  case_id            : {raw.get('case_id')}  condition={raw.get('condition')}")
    print(f"  oracle_memory_ids  : {metrics.get('oracle_memory_ids_annotated') or metrics.get('oracle_memory_ids')}")
    print(f"  precision / recall : {metrics.get('precision')} / {metrics.get('recall')}")
    print(f"  candidate_count    : {metrics.get('memory_candidate_count')}")
    print(f"  cheap_filter_fn    : {metrics.get('cheap_filter_false_negative_count')}")
    print(f"  planner_ctx_ids    : {raw.get('planner_context_memory_ids')}")
    print(f"  annotated_states   : {len(raw.get('annotated_states') or [])}")
    print(f"  replan_count       : {raw.get('replan_count')}")

    rounds = raw.get("inspection_rounds") or []
    print(f"  inspection_rounds  : {len(rounds)}")
    read_only_flags = []
    for index, entry in enumerate(rounds):
        action = entry.get("action") or {}
        impact = entry.get("impact") or {}
        read_only = impact.get("is_read_only")
        read_only_flags.append(read_only)
        print(
            f"    cycle {index}: {action.get('tool')}/{action.get('operation')} "
            f"read_only={read_only} "
            f"annotated={len(entry.get('annotated_states') or [])} "
            f"has_metrics={bool(entry.get('attribution_metrics'))}"
        )


    routed = raw.get("routing_decisions") or []
    routed_ids = sorted({d.get("memory_id") for d in routed if d.get("memory_id")})
    print(f"  routed_memory_ids  : {routed_ids}")


    orphaned = []
    for entry in rounds:
        for candidate in entry.get("annotated_states") or []:
            source = str(candidate.get("source") or "")
            if source.startswith("memory:") and "memory_id" not in candidate:
                orphaned.append(
                    {
                        "state_id": candidate.get("id"),
                        "source": source,
                        "attributed_v2": candidate.get("attributed_v2"),
                        "v2_source": candidate.get("v2_source"),
                        "passed_cheap_filter": candidate.get("passed_cheap_filter"),
                        "critical": candidate.get("critical"),
                        "delta_cf": candidate.get("delta_cf"),
                    }
                )
    if orphaned:
        print("  orphaned_candidates: scored with memory: source but no memory_id key")
        for item in orphaned:
            print(f"      {item}")

    oracle = set(metrics.get("oracle_memory_ids_annotated") or metrics.get("oracle_memory_ids") or [])
    if orphaned:
        verdict = (
            "V2_METRICS_PLUMBING_BUG: candidates were scored (some critical) but "
            "score_candidates' V2 path omits memory_id, so stage_metrics counted none"
        )
    elif read_only_flags and all(flag for flag in read_only_flags):
        verdict = (
            "COVERAGE_ARTIFACT: every inspected cycle was read-only, so main_loop "
            "returned empty attribution defaults before scoring ran"
        )
    elif not metrics.get("memory_candidate_count") and oracle & set(routed_ids):
        verdict = (
            "GROUNDER_MISS: routing resolved the oracle memory ids, but no scored "
            "candidate carried a memory: source, so attribution saw nothing"
        )
    elif not metrics.get("memory_candidate_count"):
        verdict = "NO_CANDIDATES: grounder produced no memory-sourced states"
    elif metrics.get("cheap_filter_false_negative_count"):
        verdict = "CHEAP_FILTER_MISS: oracle ids were candidates but failed the prefilter"
    else:
        verdict = "SCORED_BUT_NOT_CRITICAL: candidates passed prefilter but none marked critical"
    print(f"  VERDICT            : {verdict}")
    return verdict


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: diagnose_attribution <exported_case_dir> [...]")
    for case_dir in argv[1:]:
        diagnose(case_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
