from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
from pathlib import Path

from scaffold.statewise.agents import planner
from scaffold.statewise.core import action_model, main_loop
from scaffold.statewise.evaluation import safety_eval
from scaffold.statewise.memory import memory_store


BASE_VARIANT = "facet_binding_guard"
BASE_FINGERPRINT = (
    "sha256:281e42e2bd78a0f6fb6d48aa9c1b73a0f34ced089752b4619d2185e804e46649"
)
VARIANT = "constraint_aware_alternative_replan"
METHOD_NAME = (
    "StateWise-v2+FacetBindingGuard+ConstraintAwareAlternativeReplan"
    "+ResolvedStateFeasibilityGuard"
)

_CLEANUP_MARKERS = (
    "cleanup", "clean up", "delete", "remove", "free space",
    "清理", "删除", "移除", "释放空间",
)
_PRESERVATION_MARKERS = (
    "reviewed", "regression baseline", "golden", "signed", "audit record",
    "compliance evidence", "still referenced", "required", "legal hold",
    "preserve", "protected",
)
_AUTHORITATIVE_SOURCES = (
    "human_simulator_confirmed", "user_confirmed", "tool_verified",
    "verify_state", "ask_state",
)


def resolved_cleanup_conflict(task, state, scope=None):

    task_text = str(task or "").casefold()
    if not any(marker.casefold() in task_text for marker in _CLEANUP_MARKERS):
        return None
    for entry in memory_store.active_entries(state or {}, scope=scope).values():
        source = str(entry.get("source") or "").casefold()
        confidence = str(entry.get("confidence") or "").casefold()
        authoritative = (
            confidence in {"high", "verified", "oracle"}
            or any(marker in source for marker in _AUTHORITATIVE_SOURCES)
        )
        if not authoritative:
            continue
        value_text = str(entry.get("value") or "").casefold()
        marker = next(
            (item for item in _PRESERVATION_MARKERS if item in value_text),
            None,
        )
        if marker:
            return {
                "memory_id": entry.get("id"),
                "state_key": entry.get("key"),
                "state_value": entry.get("value"),
                "source": entry.get("source"),
                "matched_preservation_semantics": marker,
            }
    return None


def _resolved_state_feasibility_wrapper(original):
    def wrapped(
        task,
        state,
        case_id="default",
        stage_suffix="propose_action_initial",
        observation=None,
        trajectory=None,
        scope=None,
    ):
        conflict = resolved_cleanup_conflict(task, state, scope=scope)
        if conflict is None:
            return original(
                task,
                state,
                case_id=case_id,
                stage_suffix=stage_suffix,
                observation=observation,
                trajectory=trajectory,
                scope=scope,
            )
        value = str(conflict.get("state_value") or "the resolved state")
        return {
            "action": {
                "tool": "user",
                "operation": "report",
                "arguments": {
                    "message": (
                        "No cleanup mutation was executed. The authoritative "
                        f"resolved state is: {value}. This establishes a "
                        "preservation requirement, so deletion or cleanup "
                        "cannot safely proceed without a new authoritative "
                        "state change."
                    )
                },
                "target": None,
            },
            "rationale": "resolved_state_establishes_preservation_requirement",
            "resolved_state_feasibility_guard": {
                "triggered": True,
                **copy.deepcopy(conflict),
            },
        }

    return wrapped


def method_name(variant=VARIANT):
    if variant != VARIANT:
        raise ValueError(f"unknown constraint-replan variant: {variant}")
    return METHOD_NAME


def method_fingerprint(variant=VARIANT):
    payload = (
        BASE_FINGERPRINT.encode("utf-8")
        + b"\n"
        + method_name(variant).encode("utf-8")
        + b"\n"
        + Path(__file__).read_bytes()
    )
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def constraint_refusal(result):

    if not isinstance(result, dict):
        return None
    gate = result.get("residual_gate") or {}
    action = result.get("final_action")
    if (
        gate.get("decision") != "REFUSE"
        or not gate.get("constraint_id")
        or not gate.get("state_key")
        or not isinstance(action, dict)
    ):
        return None
    try:
        normalized = action_model.normalize(action)
    except (TypeError, ValueError):
        return None
    if (
        normalized.get("tool") != "git"
        or normalized.get("operation") != "force_push"
    ):
        return None
    return {
        "constraint_id": gate.get("constraint_id"),
        "reason": gate.get("reason"),
        "state_key": gate.get("state_key"),
        "state_value": copy.deepcopy(gate.get("state_value")),
        "forbidden_action": copy.deepcopy(normalized),
    }


def _same_action(left, right):
    try:
        return action_model.equivalent(left, right)
    except (TypeError, ValueError):
        return False


def _merge(initial, recovered, refusal, case):
    merged = dict(recovered)


    for field in (
        "initial_action",
        "initial_rationale",
        "planner_context_memory_ids",
        "initial_impact",
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

    recovery_action = recovered.get("final_action")
    repeated = _same_action(recovery_action, refusal["forbidden_action"])
    recovery_gate = copy.deepcopy(recovered.get("residual_gate") or {})
    if repeated and recovery_gate.get("decision") == "EXECUTE":


        recovery_gate = {
            "decision": "REFUSE",
            "reason": "repeated_state_action_constraint",
            "constraint_id": refusal["constraint_id"],
            "state_key": refusal["state_key"],
            "state_value": copy.deepcopy(refusal["state_value"]),
            "action": copy.deepcopy(refusal["forbidden_action"]),
        }
        merged["residual_gate"] = recovery_gate
        merged["safety_evaluation"] = safety_eval.evaluate(
            recovery_action,
            "REFUSE",
            case.get("safety", {}),
        )

    merged["constraint_alternative_replan"] = {
        "triggered": True,
        **copy.deepcopy(refusal),
        "recovery_action": copy.deepcopy(recovery_action),
        "recovery_gate": copy.deepcopy(recovery_gate),
        "repeated_forbidden_action": repeated,
    }
    return merged


def _constraint_replan_wrapper(original):
    def wrapped(*args, **kwargs):
        initial = original(*args, **kwargs)
        refusal = constraint_refusal(initial)
        if refusal is None:
            return initial

        observation = {
            "ok": False,
            "state_action_constraint": {
                key: copy.deepcopy(value)
                for key, value in refusal.items()
                if key != "forbidden_action"
            },
            "rejected_action": copy.deepcopy(refusal["forbidden_action"]),
            "instruction": (
                "The rejected force-push was not executed and conflicts with "
                "resolved state. Select exactly one materially different "
                "canonical task-domain action. A review-based Git operation "
                "may be used when direct writes are prohibited, but derive "
                "its branch/base from current task state. Return user.report "
                "only if no supported safe task action exists."
            ),
        }
        recovery_kwargs = dict(kwargs)
        recovery_kwargs.pop("initial_proposal", None)
        recovery_kwargs["initial_state"] = copy.deepcopy(
            initial.get("final_memory") or {}
        )
        recovery_kwargs["initial_observation"] = observation
        prior_trajectory = list(recovery_kwargs.get("trajectory") or [])
        prior_trajectory.append({
            "type": "STATE_ACTION_CONSTRAINT_REJECTED",
            "action": copy.deepcopy(refusal["forbidden_action"]),
            "constraint": {
                key: copy.deepcopy(value)
                for key, value in refusal.items()
                if key != "forbidden_action"
            },
        })
        recovery_kwargs["trajectory"] = prior_trajectory
        recovery_kwargs["initial_stage_suffix"] = (
            "constraint_alternative_replan"
        )
        recovered = original(*args, **recovery_kwargs)
        case_path = args[0] if args else kwargs.get("case_path")
        case = main_loop.load_case(case_path)
        return _merge(initial, recovered, refusal, case)

    return wrapped


@contextmanager
def use_variant(variant=VARIANT):
    method_name(variant)
    original_run_case = main_loop.run_case
    original_propose_action = planner.propose_action
    try:
        main_loop.run_case = _constraint_replan_wrapper(original_run_case)
        planner.propose_action = _resolved_state_feasibility_wrapper(
            original_propose_action
        )
        yield {
            "variant": variant,
            "method_name": method_name(variant),
            "method_fingerprint": method_fingerprint(variant),
            "base_variant": BASE_VARIANT,
            "base_fingerprint": BASE_FINGERPRINT,
            "max_alternative_replans": 1,
            "triggers": [
                "declared_git_force_push_state_action_constraint",
                "authoritative_resolved_cleanup_preservation_conflict",
            ],
        }
    finally:
        main_loop.run_case = original_run_case
        planner.propose_action = original_propose_action
