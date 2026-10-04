import argparse
import glob
import json
import os
import sys
import math

from scaffold.statewise import config
from scaffold.statewise.evaluation import case_eval

CASES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cases")


def main():


    enable_llm_judge = False

    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=3, help="repetitions per case")
    parser.add_argument("--quiet", action="store_true", help="suppress per-trial JSON dump")
    parser.add_argument("--case", action="append", dest="case_ids", help="run only this case id; repeatable")
    args = parser.parse_args()

    if config.FAKE_API:
        print(
            "config.FAKE_API is True — set STATECLARIFY_FAKE_API=false to hit the real API.",
            file=sys.stderr,
        )
        sys.exit(1)

    case_paths = sorted(glob.glob(os.path.join(CASES_DIR, "*.json")))
    if args.case_ids:
        wanted = set(args.case_ids)
        case_paths = [path for path in case_paths if os.path.splitext(os.path.basename(path))[0] in wanted]
    if not case_paths:
        print(f"No case files found under {CASES_DIR}")
        sys.exit(1)

    stats = {}
    for case_path in case_paths:
        with open(case_path, "r", encoding="utf-8") as f:
            case = json.load(f)
        case_id = case["case_id"]

        print("=" * 64)
        print(f"CASE: {case_id}  ({args.trials} trials)")
        print("=" * 64)

        pipeline_passes = 0
        declared_contract_passes = 0
        raw_catches = 0
        pipe_catches = 0
        safety_sentry_catches = 0
        safety_sentry_pipe_catches = 0
        safety_sentry_paired_trials = 0
        invariant_violations = 0
        corrupted_condition_invariant_violations = 0
        no_memory_invariant_violations = 0
        condition_contract_failures = 0
        psiaf_induction_positives = 0
        mitigation_effective_trials = 0
        candidate_recall_sum = 0.0
        prefilter_recall_sum = 0.0
        attribution_recall_sum = 0.0
        memory_candidates = 0
        counterfactual_candidates_tested = 0
        counterfactual_probes = 0
        counterfactual_candidates_filtered = 0
        cheap_filter_false_negatives = 0
        acceptable_steps = 0
        reference_action_matches = 0
        progress_steps = 0
        routing_exact = 0
        safe_escalations = 0
        primary_judge_uses = 0
        judge_calls = 0
        human_reviews = 0
        state_questions = 0
        human_simulator_calls = 0
        human_answers_known = 0
        paired_trials = 0

        for t in range(args.trials):
            try:
                results, failures = case_eval.evaluate_case(
                    case_path, case, enable_llm_judge=enable_llm_judge
                )
            except Exception as e:
                print(f"  trial {t}: ERROR {e!r}")
                continue


            condition_arms = results.get("experimental_conditions", {})
            primary = condition_arms.get("mitigated") or results.get("corrupted") or results.get("single", {})
            grade = primary.get("grade", {})


            ok = grade.get("safety_pass", False) and grade.get("acceptable_step", False)
            pipeline_passes += int(ok)


            declared_contract_passes += int(not failures)

            mitigated = condition_arms.get("mitigated", results.get("corrupted", {}))
            corrupted = condition_arms.get("corrupted", {})
            invariant_violations += int(mitigated.get("safety_evaluation", {}).get("violated", False))
            corrupted_condition_invariant_violations += int(
                corrupted.get("safety_evaluation", {}).get("violated", False)
            )
            condition_contract_failures += int(
                not results.get("experimental_condition_contract", {}).get("valid", True)
            )
            separated_contracts = results.get("experimental_contracts", {})
            psiaf_induction_positives += int(
                separated_contracts.get("psiaf_induction", {}).get("positive", False)
            )
            mitigation_effective_trials += int(
                separated_contracts.get("mitigation_efficacy", {}).get("effective", False)
            )
            no_memory_invariant_violations += int(
                results.get("no_memory", {}).get("safety_evaluation", {}).get("violated", False)
            )
            attr_metrics = (
                mitigated.get("episode_attribution_metrics")
                or mitigated.get("attribution_metrics", {})
            )
            candidate_recall_sum += attr_metrics.get("candidate", {}).get("recall", 0.0)
            prefilter_recall_sum += attr_metrics.get("prefilter", {}).get("recall", 0.0)
            attribution_recall_sum += attr_metrics.get("recall", 0.0)
            memory_candidates += attr_metrics.get("memory_candidate_count", 0)
            counterfactual_candidates_tested += attr_metrics.get("counterfactual_candidate_count", 0)
            counterfactual_probes += attr_metrics.get("counterfactual_probe_count", 0)
            counterfactual_candidates_filtered += attr_metrics.get("counterfactual_candidates_filtered", 0)
            cheap_filter_false_negatives += attr_metrics.get("cheap_filter_false_negative_count", 0)
            acceptable_steps += int(grade.get("acceptable_step", False))
            reference_action_matches += int(
                grade.get("action_exact_match", False)
                or grade.get("acceptable_action_match", False)
            )
            progress_steps += int(grade.get("task_status") == "progress")
            routing_exact += int(grade.get("routing", {}).get("exact_match", False))
            safe_escalations += int(grade.get("routing", {}).get("safe_escalation", False))
            primary_judge_uses += int(grade.get("llm_judge", {}).get("used", False))
            judge_calls += sum(
                int(value.get("grade", {}).get("llm_judge", {}).get("used", False))
                for value in results.values()
                if isinstance(value, dict)
            )
            human_reviews += int(grade.get("needs_human_review", False))
            interactions = mitigated.get("human_interactions", [])
            state_questions += len(mitigated.get("questions_asked", []))
            human_simulator_calls += len(interactions)
            human_answers_known += sum(
                int(item.get("answer", {}).get("known", False)) for item in interactions
            )

            row = case_eval.boring_but_risky_row(results)
            if row is not None:
                paired_trials += 1
                raw_catches += int(row[0])
                pipe_catches += int(row[1])

            sentry_row = case_eval.safety_sentry_catch_row(results)
            if sentry_row is not None:
                safety_sentry_paired_trials += 1
                safety_sentry_catches += int(sentry_row[0])
                safety_sentry_pipe_catches += int(sentry_row[1])

            if args.quiet:
                extra = ""
                if row is not None:
                    extra = f"  (raw={'Y' if row[0] else 'N'} pipe={'Y' if row[1] else 'N'})"
                print(
                    f"  trial {t}: {'ACCEPT' if ok else grade.get('task_status', 'FAIL').upper()}"
                    f" basis={grade.get('action_grade_basis')} routing_exact={grade.get('routing', {}).get('exact_match')}"
                    f" judge={grade.get('llm_judge', {}).get('used', False)}{extra}"
                )
                if failures and not ok:
                    for fmsg in failures:
                        print(f"      - {fmsg}")
            else:
                print(f"--- trial {t} [{'PASS' if ok else 'FAIL'}] ---")
                print(json.dumps(results, indent=2, ensure_ascii=False))
                for fmsg in failures:
                    print(f"  - {fmsg}")

        stats[case_id] = {
            "pipeline_passes": pipeline_passes,
            "declared_contract_passes": declared_contract_passes,
            "trials": args.trials,
            "raw_catches": raw_catches,
            "pipe_catches": pipe_catches,
            "paired_trials": paired_trials,
            "safety_sentry_catches": safety_sentry_catches,
            "safety_sentry_pipe_catches": safety_sentry_pipe_catches,
            "safety_sentry_paired_trials": safety_sentry_paired_trials,
            "invariant_violations": invariant_violations,
            "corrupted_condition_invariant_violations": corrupted_condition_invariant_violations,
            "no_memory_invariant_violations": no_memory_invariant_violations,
            "condition_contract_failures": condition_contract_failures,
            "psiaf_induction_positives": psiaf_induction_positives,
            "mitigation_effective_trials": mitigation_effective_trials,
            "mean_candidate_recall": candidate_recall_sum / args.trials if args.trials else 0.0,
            "mean_prefilter_recall": prefilter_recall_sum / args.trials if args.trials else 0.0,
            "mean_attribution_recall": attribution_recall_sum / args.trials if args.trials else 0.0,
            "memory_candidates": memory_candidates,
            "counterfactual_candidates_tested": counterfactual_candidates_tested,
            "counterfactual_probes": counterfactual_probes,
            "counterfactual_candidates_filtered": counterfactual_candidates_filtered,
            "cheap_filter_false_negatives": cheap_filter_false_negatives,
            "acceptable_steps": acceptable_steps,
            "reference_action_matches": reference_action_matches,
            "progress_steps": progress_steps,
            "routing_exact": routing_exact,
            "safe_escalations": safe_escalations,
            "primary_judge_uses": primary_judge_uses,
            "judge_calls": judge_calls,
            "human_reviews": human_reviews,
            "state_questions": state_questions,
            "human_simulator_calls": human_simulator_calls,
            "human_answers_known": human_answers_known,
        }

    _print_summary(stats)


    if any(
        s["invariant_violations"] > 0 or s["no_memory_invariant_violations"] > 0
        for s in stats.values()
    ):
        sys.exit(1)


def _print_summary(stats):
    print("\n" + "=" * 64)
    print("DECISION-LEVEL SUMMARY (no action execution; no episode completion claim)")
    print("=" * 64)
    for case_id, s in stats.items():
        flag = " <-- no acceptable step" if s["pipeline_passes"] == 0 else ""
        low, high = _wilson_interval(s["pipeline_passes"], s["trials"])
        print(
            f"  pipeline {s['pipeline_passes']}/{s['trials']} "
            f"(95% Wilson {low:.2f}-{high:.2f}); decision-contract "
            f"{s['declared_contract_passes']}/{s['trials']}; episode-evaluable=0/{s['trials']}; "
            f"attr-recall candidate/prefilter/final="
            f"{s['mean_candidate_recall']:.2f}/{s['mean_prefilter_recall']:.2f}/{s['mean_attribution_recall']:.2f}; "
            f"cf-candidates={s['counterfactual_candidates_tested']}/{s['memory_candidates']} "
            f"probes={s['counterfactual_probes']} filtered={s['counterfactual_candidates_filtered']} "
            f"filter-FN={s['cheap_filter_false_negatives']}; "
            f"reference-action-match={s['reference_action_matches']}/{s['trials']}; "
            f"decision-progress={s['progress_steps']}/{s['trials']}; "
            f"routing-exact={s['routing_exact']}/{s['trials']}; safe-escalation={s['safe_escalations']}/{s['trials']}; "
            f"primary-judge-used={s['primary_judge_uses']}/{s['trials']}; "
            f"judge-calls={s['judge_calls']}; review={s['human_reviews']}/{s['trials']}; "
            f"ask-state={s['state_questions']} human-sim-calls={s['human_simulator_calls']} "
            f"known-answers={s['human_answers_known']}; "
            f"mitigated-violations={s['invariant_violations']} "
            f"corrupted-violations={s['corrupted_condition_invariant_violations']} "
            f"condition-contract-failures={s['condition_contract_failures']}; "
            f"psiaf-induction={s['psiaf_induction_positives']}/{s['trials']} "
            f"mitigation-effective={s['mitigation_effective_trials']}/{s['trials']}; "
            f"no-memory-violations={s['no_memory_invariant_violations']}  {case_id}{flag}"
        )

    print("\n" + "=" * 64)
    print("BORING-BUT-RISKY CATCH RATES (corrupted condition, over trials)")
    print("  raw = action-only gate flagged it | pipe = full pipeline intervened")
    print("=" * 64)
    for case_id, s in stats.items():
        if s["paired_trials"] == 0:
            continue
        print(
            f"  raw {s['raw_catches']}/{s['paired_trials']}   "
            f"pipe {s['pipe_catches']}/{s['paired_trials']}   {case_id}"
        )

    print("\n" + "=" * 64)
    print("B8 SAFETY-SENTRY-STYLE BASELINE CATCH RATES (corrupted condition)")
    print("  b8 = EXECUTE/ASK/REFUSE router flagged it | pipe = full pipeline intervened")
    print("=" * 64)
    for case_id, s in stats.items():
        if s["safety_sentry_paired_trials"] == 0:
            continue
        print(
            f"  b8 {s['safety_sentry_catches']}/{s['safety_sentry_paired_trials']}   "
            f"pipe {s['safety_sentry_pipe_catches']}/{s['safety_sentry_paired_trials']}   {case_id}"
        )


def _wilson_interval(successes, trials, z=1.96):
    if trials == 0:
        return 0.0, 0.0
    p = successes / trials
    denominator = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * trials)) / trials) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


if __name__ == "__main__":
    main()
