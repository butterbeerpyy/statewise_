from __future__ import annotations

from contextlib import contextmanager
import hashlib
from pathlib import Path
import re

from scaffold.statewise import config
from scaffold.statewise.agents import planner
from scaffold.statewise.core import action_model, attribution, critical_detect, interceptor, reliability, route
from scaffold.statewise.memory import memory_store


BASE_METHOD = "StateWise-v0"
BASE_FINGERPRINT = "sha256:4a7e51297ba462c473af057a7c80bfb604381bece30c706e598ff1a254eee0a2"
VARIANTS = {
    "v0": BASE_METHOD,
    "hybrid": "StateWise-v0+HybridMultiStateAttribution",
    "progress": "StateWise-v0+ProgressMonitor",
    "hybrid_joint": "StateWise-v0+HybridMultiStateAttribution+JointEvidenceResolver",
    "combined": "StateWise-v0+HybridMultiStateAttribution+JointEvidenceResolver+ProgressMonitor",


    "no_attribution": "StateWise-final-Ablation-NoAttribution",
    "no_repair": "StateWise-final-Ablation-NoPersistentRepair",
    "no_counterfactual": "StateWise-final-Ablation-NoCounterfactual",
}


def method_name(variant):
    if variant not in VARIANTS:
        raise ValueError(f"unknown targeted variant: {variant}")
    return VARIANTS[variant]


def method_fingerprint(variant):
    source = Path(__file__).read_bytes()
    payload = BASE_FINGERPRINT.encode("utf-8") + b"\n" + method_name(variant).encode("utf-8") + b"\n" + source
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def promote_hybrid_candidates(scored):

    recovered = []
    for item in scored:
        promoted = dict(item)
        if (
            promoted.get("memory_id")
            and promoted.get("provenance_link")
            and not promoted.get("passed_cheap_filter")
        ):
            promoted["passed_cheap_filter"] = True
            promoted["filter_reason"] = "hybrid_provenance_counterfactual_recovery"
            promoted["attribution_variant"] = "hybrid_multistate"
        recovered.append(promoted)
    return recovered


def _successful_read_only_count(trajectory):
    count = 0
    for event in reversed(tuple(trajectory or ())):
        if not isinstance(event, dict):
            continue
        action = event.get("action")
        if not isinstance(action, dict):
            continue
        try:
            read_only = interceptor.classify(action)["is_read_only"]
        except (TypeError, ValueError):
            break
        if not read_only:
            break
        result = event.get("result", {})
        action_result = result.get("action_result", {}) if isinstance(result, dict) else {}
        if bool(action_result.get("ok")) or bool(result.get("ok") if isinstance(result, dict) else False):
            count += 1
    return count


def progress_trigger(result, trajectory):

    if not isinstance(result, dict) or not trajectory:
        return None
    action = result.get("action")
    if not isinstance(action, dict):
        return None
    normalized = action_model.normalize(action)
    if normalized["tool"] == "user" and normalized["operation"] == "report":
        return "premature_report_candidate"
    try:
        proposed_read_only = interceptor.classify(normalized)["is_read_only"]
    except (TypeError, ValueError):
        proposed_read_only = False
    if proposed_read_only and _successful_read_only_count(trajectory) >= 2:
        return "read_only_stagnation"
    return None


def _hybrid_score_wrapper(original):
    def wrapped(*args, **kwargs):
        return promote_hybrid_candidates(original(*args, **kwargs))
    return wrapped


def _canonical_value_tokens(value):
    return {
        token
        for token in re.findall(r"[a-z][a-z0-9._-]*", str(value).lower())
        if token not in {"true", "false", "none", "unknown", "only", "current", "default"}
    }


def joint_consensus_value(state, case):

    environment = (case or {}).get("environment", {})
    supporters = {}
    for entry in memory_store.active_entries(
        state, scope=environment.get("scope")
    ).values():
        score = reliability.score(
            entry,
            state,
            current_scope=environment.get("scope"),
            as_of=environment.get("as_of"),
        )["reliability"]
        if score < route.RELIABILITY_THRESHOLD:
            continue
        for token in _canonical_value_tokens(entry.get("value")):


            pieces = {token} | set(token.replace("_", "-").split("-"))
            for piece in pieces:
                if len(piece) >= 3:
                    supporters.setdefault(piece, []).append(entry["id"])
    consensus = {
        value: sorted(set(ids))
        for value, ids in supporters.items()
        if len(set(ids)) >= 2
    }
    if len(consensus) != 1:
        return None
    value, memory_ids = next(iter(consensus.items()))
    return {"value": value, "memory_ids": memory_ids}


def _joint_route_wrapper(original):
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
        consensus = joint_consensus_value(state, case or {})
        if consensus is None:
            return decisions
        resolved = []
        for decision in decisions:
            if decision.get("method") != "ABSTAIN" or not decision.get("memory_id"):
                resolved.append(decision)
                continue
            entry = state.get(decision["memory_id"], {})
            current_tokens = _canonical_value_tokens(entry.get("value"))
            if consensus["value"] in current_tokens:
                resolved.append(decision)
                continue
            resolved.append({
                **decision,
                "method": "VERIFY_STATE",
                "reason": "joint_reliable_evidence_consensus",
                "machine_resolved": True,
                "verified_value": consensus["value"],
                "tool": "joint_reliable_memory_consensus",
                "verification_status": "CONFIRMED",
                "evidence": {
                    "supporting_memory_ids": consensus["memory_ids"],
                    "canonical_value": consensus["value"],
                },
            })
        return resolved
    return wrapped


def _progress_planner_wrapper(original):
    def wrapped(
        task,
        state,
        case_id="default",
        stage_suffix="propose_action_initial",
        observation=None,
        trajectory=None,
        scope=None,
    ):
        result = original(
            task,
            state,
            case_id=case_id,
            stage_suffix=stage_suffix,
            observation=observation,
            trajectory=trajectory,
            scope=scope,
        )
        reason = progress_trigger(result, trajectory)
        if reason is None or config.FAKE_API:
            return result
        directive = (
            "\n\nProgress-monitor directive: the previous episode steps have not "
            "yet satisfied the task. Consume the observations and perform one "
            "bounded recovery replan. Prefer a concrete lower-risk task action "
            "that respects verified constraints (for example a proposal/PR "
            "instead of a direct protected-branch push). Do not repeat prior "
            "read-only actions. Keep user.report only when reporting itself is "
            "the task's legitimate requested terminal outcome."
        )
        retried = original(
            task + directive,
            state,
            case_id=case_id,
            stage_suffix=f"{stage_suffix}_progress_monitor",
            observation=observation,
            trajectory=trajectory,
            scope=scope,
        )
        return {
            **retried,
            "progress_monitor": {
                "triggered": True,
                "reason": reason,
                "replaced_action": result.get("action"),
            },
        }
    return wrapped


@contextmanager
def use_variant(variant):

    if variant not in VARIANTS:
        raise ValueError(f"unknown targeted variant: {variant}")
    original_score = attribution.score_candidates
    original_propose = planner.propose_action
    original_route = route.route
    original_detect = critical_detect.detect
    try:
        if variant in {"hybrid", "hybrid_joint", "combined"}:
            attribution.score_candidates = _hybrid_score_wrapper(original_score)
        if variant in {"hybrid_joint", "combined"}:
            route.route = _joint_route_wrapper(original_route)
        if variant in {"progress", "combined"}:
            planner.propose_action = _progress_planner_wrapper(original_propose)
        if variant == "no_attribution":


            attribution.score_candidates = lambda *args, **kwargs: []
        elif variant == "no_counterfactual":


            critical_detect.detect = lambda *args, **kwargs: []
        elif variant == "no_repair":


            def _no_repair_route(*args, **kwargs):
                decisions = original_route(*args, **kwargs)
                return [
                    ({**decision, "method": "REFUSE",
                      "reason": "ablation_no_persistent_repair"}
                     if decision.get("method") in {"VERIFY_STATE", "ASK_STATE"}
                     else decision)
                    for decision in decisions
                ]
            route.route = _no_repair_route
        yield {
            "variant": variant,
            "method_name": method_name(variant),
            "method_fingerprint": method_fingerprint(variant),
        }
    finally:
        attribution.score_candidates = original_score
        planner.propose_action = original_propose
        route.route = original_route
        critical_detect.detect = original_detect
