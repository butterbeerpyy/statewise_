from __future__ import annotations

import copy
from contextlib import contextmanager, nullcontext
import hashlib
from pathlib import Path

from scaffold.statewise.core import attribution, main_loop, route
from scaffold.statewise.experiments import attribution_v2, attribution_v2_typed
from scaffold.statewise.memory import memory_repair
from scaffold.statewise.runtime import tools


BASE_VARIANT = "retrieval_slots_conflict"
BASE_FINGERPRINT = (
    "sha256:abee2899b4d171402d87101528cee8966bfebd023add93bf38b83ce5fd6bbedd"
)
MAX_RETRIEVAL_CANDIDATES = 12
SLOT_CANDIDATE_QUOTA = 2
VARIANTS = {
    "facet_binding_guard": (
        "StateWise-v2+FacetCoverage+ConflictSets+BindingGuard"
        "+SchemaEvidenceContinuation"
    ),
    "topk12_slots2": (
        "StateWise-v2+SlotConflict+TopK12+TwoPerSlot"
    ),
    "topk12_slots2_binding_guard": (
        "StateWise-v2+SlotConflict+TopK12+TwoPerSlot+BindingGuard"
    ),
}


def _schema_verification_continuation_wrapper(original):


    def wrapped(*args, **kwargs):
        initial = original(*args, **kwargs)
        gate = initial.get("residual_gate") or {}
        schema_errors = list(initial.get("action_schema_errors") or [])
        verified = [
            decision
            for decision in initial.get("routing_decisions", []) or []
            if (
                decision.get("method") == "VERIFY_STATE"
                and decision.get("machine_resolved")
                and decision.get("key")
                and "verified_value" in decision
            )
        ]
        if gate.get("reason") != "invalid_action_schema" or not verified:
            return initial

        case_path = args[0] if args else kwargs.get("case_path")
        case = main_loop.load_case(case_path)
        repaired_state = copy.deepcopy(initial.get("final_memory") or {})
        committed = []
        for decision in verified:
            new_memory_id = memory_repair.repair(
                repaired_state,
                key=decision["key"],
                value=decision["verified_value"],
                source=f"tool_verified:{decision.get('tool', 'unknown')}",
                confidence="high",
                evidence={
                    "tool": decision.get("tool"),
                    "detail": decision.get("evidence"),
                    "continuation": "schema_verification_replan",
                },
                scope=case.get("environment", {}).get("scope"),
                supersede_id=decision.get("memory_id"),
            )
            committed.append(
                {
                    "key": decision["key"],
                    "value": decision["verified_value"],
                    "memory_id": new_memory_id,
                    "supersedes": decision.get("memory_id"),
                }
            )

        recovery_kwargs = dict(kwargs)
        recovery_kwargs.pop("initial_proposal", None)
        recovery_kwargs["initial_state"] = repaired_state
        schema_observation = {
            "ok": False,
            "runtime_error": {
                "type": "invalid_action_schema",
                "errors": schema_errors,
            },
        }
        recovery_kwargs["initial_observation"] = schema_observation
        prior_trajectory = list(recovery_kwargs.get("trajectory") or [])
        prior_trajectory.append(
            {
                "type": "PLAN_REJECTED",
                "action": copy.deepcopy(initial.get("final_action")),
                "runtime_error": schema_observation["runtime_error"],
            }
        )
        recovery_kwargs["trajectory"] = prior_trajectory
        recovery_kwargs["initial_stage_suffix"] = (
            "schema_verification_replan"
        )
        recovered = original(*args, **recovery_kwargs)

        merged = dict(recovered)
        for field in (
            "initial_action",
            "initial_rationale",
            "planner_context_memory_ids",
            "initial_impact",
            "support_states",
            "annotated_states",
            "attribution_metrics",
            "critical_states",
        ):
            if field in initial:
                merged[field] = copy.deepcopy(initial[field])
        for field in (
            "inspection_rounds",
            "routing_decisions",
            "questions_asked",
            "human_interactions",
        ):
            merged[field] = (
                copy.deepcopy(initial.get(field) or [])
                + copy.deepcopy(recovered.get(field) or [])
            )
        merged["replan_count"] = (
            int(initial.get("replan_count") or 0)
            + 1
            + int(recovered.get("replan_count") or 0)
        )
        merged["schema_verification_continuation"] = {
            "triggered": True,
            "schema_errors": schema_errors,
            "committed_verifications": committed,
            "recovery_gate": copy.deepcopy(
                recovered.get("residual_gate") or {}
            ),
        }
        return merged

    return wrapped


def method_name(variant):
    if variant not in VARIANTS:
        raise ValueError(f"unknown simple Attribution-v2 variant: {variant}")
    return VARIANTS[variant] + "+TypedActionSlotGrounding"


def method_fingerprint(variant):
    payload = (
        BASE_FINGERPRINT.encode("utf-8")
        + b"\n"
        + attribution_v2_typed.method_fingerprint().encode("utf-8")
        + b"\n"
        + method_name(variant).encode("utf-8")
        + b"\n"
        + Path(__file__).read_bytes()
    )
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _slot_two_stratified_ranked(ranked, action):

    selected = []
    selected_ids = set()
    for slot in attribution_v2.action_state_slots(action):
        slot_count = 0
        for item in ranked:
            memory_id = item[2]["id"]
            if memory_id in selected_ids or slot not in item[6]:
                continue
            selected.append(item)
            selected_ids.add(memory_id)
            slot_count += 1
            if len(selected) >= MAX_RETRIEVAL_CANDIDATES:
                return selected
            if slot_count >= SLOT_CANDIDATE_QUOTA:
                break
    for item in ranked:
        memory_id = item[2]["id"]
        if memory_id in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(memory_id)
        if len(selected) >= MAX_RETRIEVAL_CANDIDATES:
            break
    return selected


def _direct_argument_binding(candidate):
    source = str(candidate.get("source") or "")
    slots = set(candidate.get("candidate_state_slots") or ())
    return bool(
        source.startswith("memory:")
        and candidate.get("memory_id")
        and candidate.get("provenance_link")
        and "typed_grounding_incompatible"
        not in candidate.get("grounding_basis", [])
        and candidate.get("filter_reason")
        != "v2_typed_grounding_incompatible"
        and (
            candidate.get("relation") == "used_to_fill_argument"
            or candidate.get("supported_argument")
            or any(slot.startswith("argument:") for slot in slots)
        )
    )


def _binding_guard_finalize_wrapper(original):

    def wrapped(scored_candidates, counterfactual_results, policy=None):
        finalized = original(
            scored_candidates,
            counterfactual_results,
            policy=policy,
        )
        for item in finalized:
            if (
                item.get("critical")
                or not _direct_argument_binding(item)
            ):
                continue
            item["binding_guard_forced_resolution"] = True
            item["binding_guard_trigger"] = (
                "direct_binding_unstable_after_counterfactual"
                if item.get("counterfactual_tested")
                else "direct_binding_not_counterfactually_probed"
            )
            item["critical"] = True
            item["critical_basis"] = "v2_binding_guard_unresolved_premise"
        return finalized

    return wrapped


def _binding_guard_route_wrapper(original):

    def wrapped(
        critical_states,
        state,
        action_impact,
        case=None,
        human_authoritative_keys=None,
        verification_context=None,
    ):
        decisions = original(
            critical_states,
            state,
            action_impact,
            case=case,
            human_authoritative_keys=human_authoritative_keys,
            verification_context=verification_context,
        )
        critical_by_id = {
            item.get("id"): item for item in critical_states
        }
        authoritative = set(human_authoritative_keys or ())
        guarded = []
        for decision in decisions:
            critical = critical_by_id.get(decision.get("state_id")) or {}
            if (
                not critical.get("binding_guard_forced_resolution")
                or decision.get("method") != "CONTINUE"
                or int(action_impact.get("impact_score") or 0) < 2
            ):
                guarded.append(decision)
                continue
            source = str(critical.get("source") or "")
            memory_id = (
                source.split(":", 1)[1]
                if source.startswith("memory:")
                else None
            )
            entry = state.get(memory_id) if memory_id else None
            if entry is None:
                guarded.append({
                    **decision,
                    "method": "ABSTAIN",
                    "reason": "binding_guard_source_unresolvable",
                    "evidence_reliable": False,
                    "machine_resolved": False,
                    "user_authoritative": False,
                    "binding_guard": True,
                })
                continue
            key = entry["key"]
            verification = tools.try_verify(
                key,
                state,
                memory_id=memory_id,
                context=verification_context,
            )
            status = verification.get("status", "INSUFFICIENT")
            base = {
                **decision,
                "key": key,
                "memory_id": memory_id,
                "evidence_reliable": False,
                "binding_guard": True,
                "binding_guard_trigger": critical.get(
                    "binding_guard_trigger"
                ),
            }
            if status in route.RESOLVED_VERIFICATION_STATUSES:
                guarded.append({
                    **base,
                    "method": "VERIFY_STATE",
                    "reason": "binding_guard_machine_verification_conclusive",
                    "machine_resolved": True,
                    "verified_value": verification["value"],
                    "tool": verification["tool"],
                    "evidence": verification.get("evidence"),
                    "verification_status": status,
                })
            elif key in authoritative:
                guarded.append({
                    **base,
                    "method": "ASK_STATE",
                    "reason": "binding_guard_requires_authoritative_state",
                    "machine_resolved": False,
                    "verification_status": status,
                    "user_authoritative": True,
                })
            else:
                guarded.append({
                    **base,
                    "method": "ABSTAIN",
                    "reason": "binding_guard_has_no_resolution_source",
                    "machine_resolved": False,
                    "verification_status": status,
                    "user_authoritative": False,
                })
        return guarded

    return wrapped


@contextmanager
def candidate_policy():

    original_cap = attribution_v2.MAX_RETRIEVAL_CANDIDATES
    original_ranker = attribution_v2._slot_stratified_ranked
    attribution_v2.MAX_RETRIEVAL_CANDIDATES = MAX_RETRIEVAL_CANDIDATES
    attribution_v2._slot_stratified_ranked = _slot_two_stratified_ranked
    try:
        yield
    finally:
        attribution_v2.MAX_RETRIEVAL_CANDIDATES = original_cap
        attribution_v2._slot_stratified_ranked = original_ranker


@contextmanager
def use_variant(variant):

    method_name(variant)
    candidate_context = (
        candidate_policy()
        if variant in {
            "topk12_slots2",
            "topk12_slots2_binding_guard",
        }
        else nullcontext()
    )
    with candidate_context:
        with attribution_v2.use_variant(BASE_VARIANT):
            with attribution_v2_typed.use_variant():
                original_finalize = attribution.finalize
                original_route = route.route
                original_run_case = main_loop.run_case
                try:
                    if variant in {
                        "facet_binding_guard",
                        "topk12_slots2_binding_guard",
                    }:
                        attribution.finalize = _binding_guard_finalize_wrapper(
                            original_finalize
                        )
                        route.route = _binding_guard_route_wrapper(
                            original_route
                        )
                        main_loop.run_case = (
                            _schema_verification_continuation_wrapper(
                                original_run_case
                            )
                        )
                    yield {
                        "variant": variant,
                        "method_name": method_name(variant),
                        "method_fingerprint": method_fingerprint(variant),
                        "base_variant": BASE_VARIANT,
                        "base_fingerprint": BASE_FINGERPRINT,
                        "typed_grounding_fingerprint": (
                            attribution_v2_typed.method_fingerprint()
                        ),
                        "retrieval_top_k": (
                            MAX_RETRIEVAL_CANDIDATES
                            if variant.startswith("topk12")
                            else attribution_v2.MAX_RETRIEVAL_CANDIDATES
                        ),
                        "slot_candidate_quota": (
                            SLOT_CANDIDATE_QUOTA
                            if variant.startswith("topk12")
                            else 1
                        ),
                        "counterfactual_probe_budget": (
                            attribution_v2.MAX_RETRIEVAL_CF_PROBES
                        ),
                    }
                finally:
                    attribution.finalize = original_finalize
                    route.route = original_route
                    main_loop.run_case = original_run_case
