from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping

from scaffold.statewise import config
from scaffold.statewise.agents import planner
from scaffold.statewise.core import action_model, interceptor
from scaffold.statewise.evaluation import safety_eval
from scaffold.statewise.experiments import (
    attribution_v2,
    ask_or_assume_baseline,
    baseline_interactions,
    critic_tool_grounded_baseline,
    experimental_conditions,
    live_refresh_baseline,
    memlineage_baseline,
    safety_sentry_baseline,
    targeted_variants,
)
from scaffold.statewise.memory import memory_repair, memory_store
from scaffold.statewise.runtime import lightweight_runtime


CORE_PILOT_ARMS = (
    "correct",
    "corrupted",
    "no_memory",
    "rationale_approval",
    "generic_clarification",
    "statewise_v1",
    "oracle_statewise",
)

OPTIONAL_EXECUTABLE_ARMS = (
    "auto_execute",
    "bare_approval",
    "ask_or_assume",
    "safety_sentry",
    "memlineage_trust",
    "live_refresh",
    "critic_tool_grounded",
    "statewise_v2_retrieval",
    "v1_no_attribution",
    "v1_no_repair",
    "v1_no_counterfactual",
)


FORMAL_PILOT_ARMS = (
    "correct",
    "corrupted",
    "no_memory",
    "auto_execute",
    "bare_approval",
    "rationale_approval",
    "generic_clarification",
    "safety_sentry",
    "memlineage_trust",
    "statewise_v1",
    "oracle_statewise",
)


@dataclass(frozen=True)
class ArmDefinition:
    name: str
    md_id: str | None
    label: str
    implemented: bool
    default: bool
    memory_condition: str
    statewise_enabled: bool = False
    oracle_assisted: bool = False
    reason: str | None = None


ARM_REGISTRY = {
    "correct": ArmDefinition(
        "correct", "B0", "Correct-Memory Oracle", True, True, "correct"
    ),
    "no_memory": ArmDefinition(
        "no_memory", "B1", "No Memory", True, True, "no_memory"
    ),
    "auto_execute": ArmDefinition(
        "auto_execute", "B2", "Auto Execute", True, False, "corrupted"
    ),
    "bare_approval": ArmDefinition(
        "bare_approval", "B3", "Bare Action Approval", True, False, "corrupted"
    ),
    "rationale_approval": ArmDefinition(
        "rationale_approval", "B4", "Rationale-Augmented Approval", True, True, "corrupted"
    ),
    "plan_approval": ArmDefinition(
        "plan_approval", "B5", "Plan-Level Approval", False, False, "corrupted",
        reason="deferred until the agent exposes an executable multi-step plan contract",
    ),
    "generic_clarification": ArmDefinition(
        "generic_clarification", "B6", "Generic Clarification", True, True, "corrupted"
    ),
    "ask_or_assume": ArmDefinition(
        "ask_or_assume", "B7", "Ask-or-Assume Clean-Room Reproduction", True, False,
        "corrupted",
    ),
    "safety_sentry": ArmDefinition(
        "safety_sentry", "B8", "Safety Sentry Zero-Shot Reproduction", True, False, "corrupted"
    ),
    "voi_clarification": ArmDefinition(
        "voi_clarification", "B9", "VoI Clarification", False, False, "corrupted",
        reason="deferred to Tier 2 after human-cost calibration",
    ),
    "verify_only": ArmDefinition(
        "verify_only", "B10", "Verify Only", False, False, "corrupted",
        reason="deferred to the ablation phase",
    ),
    "memlineage_trust": ArmDefinition(
        "memlineage_trust", "B11", "MemLineage-Style Trusted-Lineage Gate", True, False, "corrupted",
    ),
    "live_refresh": ArmDefinition(
        "live_refresh", None, "Simple Live State Refresh", True, False,
        "corrupted",
    ),
    "critic_tool_grounded": ArmDefinition(
        "critic_tool_grounded", "B13",
        "CRITIC-Style Tool-Grounded Self-Correction", True, False, "corrupted",
    ),
    "oracle_statewise": ArmDefinition(
        "oracle_statewise", "B12", "Oracle StateWise", True, True, "corrupted",
        statewise_enabled=True, oracle_assisted=True,
    ),
    "corrupted": ArmDefinition(
        "corrupted", None, "Untreated Corrupted Control", True, True, "corrupted"
    ),
    "statewise_v1": ArmDefinition(
        "statewise_v1", None, "StateWise-v1", True, True, "corrupted",
        statewise_enabled=True,
    ),


    "statewise_v2_retrieval": ArmDefinition(
        "statewise_v2_retrieval",
        None,
        "StateWise-v2 Retrieval",
        True,
        False,
        "corrupted",
        statewise_enabled=True,
    ),
    "v1_no_attribution": ArmDefinition(
        "v1_no_attribution", None, "StateWise-final − Attribution", True, False,
        "corrupted", statewise_enabled=True,
    ),
    "v1_no_repair": ArmDefinition(
        "v1_no_repair", None, "StateWise-final − Persistent Repair", True, False,
        "corrupted", statewise_enabled=True,
    ),
    "v1_no_counterfactual": ArmDefinition(
        "v1_no_counterfactual", None, "StateWise-final − Counterfactual", True, False,
        "corrupted", statewise_enabled=True,
    ),
}


SHARED_CORRUPTED_PROPOSAL_ARMS = frozenset({
    "corrupted",
    "auto_execute",
    "bare_approval",
    "rationale_approval",
    "generic_clarification",
    "ask_or_assume",
    "safety_sentry",
    "memlineage_trust",
    "live_refresh",
    "critic_tool_grounded",
    "statewise_v1",
    "statewise_v2_retrieval",
    "oracle_statewise",
    "v1_no_attribution",
    "v1_no_repair",
    "v1_no_counterfactual",
})
MAX_GENERIC_QUESTIONS = 2


def arm_definition(name: str) -> ArmDefinition:
    if name not in ARM_REGISTRY:
        raise ValueError(f"unknown pilot arm: {name}")
    definition = ARM_REGISTRY[name]
    if not definition.implemented:
        raise ValueError(f"pilot arm {name} is deferred: {definition.reason}")
    return definition


def registry_manifest() -> dict[str, Any]:
    manifest = {
        name: {
            "md_id": item.md_id,
            "label": item.label,
            "implemented": item.implemented,
            "default": item.default,
            "memory_condition": item.memory_condition,
            "statewise_enabled": item.statewise_enabled,
            "oracle_assisted": item.oracle_assisted,
            "reason": item.reason,
        }
        for name, item in ARM_REGISTRY.items()
    }
    manifest["safety_sentry"]["implementation"] = safety_sentry_baseline.fidelity_manifest()
    manifest["memlineage_trust"]["implementation"] = memlineage_baseline.fidelity_manifest()
    manifest["ask_or_assume"]["implementation"] = ask_or_assume_baseline.fidelity_manifest()
    manifest["critic_tool_grounded"]["implementation"] = (
        critic_tool_grounded_baseline.fidelity_manifest()
    )
    manifest["oracle_statewise"]["implementation"] = {
        "contract": "direct_decision_critical_state_truth_before_replan",
        "privileged_inputs": ["oracle_support_states", "ground_truth_state(s)"],
        "pairing": "preserve_shared_corrupted_initial_proposal",
        "repair": "suppress_applicable_same_key_stale_records_then_scoped_insert",
        "post_repair_policy": "existing_state_action_and_residual_permission_gates",
        "privilege_isolation": "oracle_arm_only",
    }
    manifest["statewise_v2_retrieval"]["implementation"] = {
        "variant": "retrieval",
        "method_name": attribution_v2.method_name("retrieval"),
        "fingerprint": attribution_v2.method_fingerprint("retrieval"),
        "base": "frozen StateWise-v1",
        "oracle_assisted": False,
    }
    for name in ("correct", "corrupted", "no_memory", "generic_clarification", "ask_or_assume"):
        manifest[name]["execution_gate_policy"] = experimental_conditions.UNTREATED_GATE_POLICY
    return manifest


def uses_shared_corrupted_proposal(name: str) -> bool:
    return name in SHARED_CORRUPTED_PROPOSAL_ARMS


def _condition_state(
    case: Mapping[str, Any],
    condition: str,
    initial_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if initial_state is not None:
        return copy.deepcopy(initial_state)
    state = memory_store.default_state()
    from scaffold.statewise.core import main_loop

    return main_loop.apply_condition(state, case, condition)


def build_proposal(
    case: Mapping[str, Any],
    condition: str,
    initial_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    state = _condition_state(case, condition, initial_state)
    suffix = {
        "correct": "propose_action_initial_correct",
        "no_memory": "propose_action_initial_no_memory",
    }.get(condition, "propose_action_initial")
    proposal = planner.propose_action(
        case["task"],
        state,
        case_id=case["case_id"],
        stage_suffix=suffix,
        scope=case.get("environment", {}).get("scope"),
    )
    return {
        **proposal,
        "planner_context_memory_ids": proposal.get(
            "planner_context_memory_ids",
            sorted(memory_store.active_entries(
                state, scope=case.get("environment", {}).get("scope")
            )),
        ),
    }


def _proposal_from_result(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "action": copy.deepcopy(result.get("final_action")),
        "rationale": result.get("initial_rationale", ""),
        "planner_context_memory_ids": list(
            result.get("planner_context_memory_ids", [])
        ),
    }


def _untreated_continuation(case: Mapping[str, Any], condition: str):
    def factory(sandbox):
        def continue_after_observation(previous, observation, trajectory):
            state = previous.get("final_memory")
            proposal = planner.propose_action(
                case["task"],
                state,
                case_id=case["case_id"],
                stage_suffix=f"episode_step_{len(trajectory)}_{condition}",
                observation=observation,
                trajectory=trajectory,
                scope=case.get("environment", {}).get("scope"),
            )
            return experimental_conditions.build_untreated_arm(
                case, condition, proposal=proposal, state=state
            )

        return continue_after_observation

    return factory


def _approval_result(
    case: Mapping[str, Any],
    state: Mapping[str, Any],
    proposal: Mapping[str, Any],
    arm: str,
    *,
    trajectory=None,
    stage_suffix="initial",
) -> dict[str, Any]:
    proposal = copy.deepcopy(proposal)
    action = action_model.contextualize(proposal["action"], state)
    schema_errors = action_model.validate(action)
    impact = interceptor.classify(action) if not schema_errors else {}
    rationale = str(proposal.get("rationale", ""))
    question = None
    if schema_errors:
        gate = {
            "decision": "REFUSE",
            "reason": "invalid_action_schema",
            "schema_errors": schema_errors,
        }
    elif arm == "auto_execute":
        gate = {"decision": "EXECUTE", "reason": "auto_execute", "impact": impact}
    elif arm == "safety_sentry":
        routed = safety_sentry_baseline.route_action(
            case,
            state,
            {**proposal, "action": action},
            prior_trace=trajectory,
            stage_suffix=stage_suffix,
        )
        if routed["decision"] == "ASK":
            question = routed.get("question")
            gate = {
                "decision": "ASK_PERMISSION",
                "reason": routed.get("reason"),
                "impact": impact,
                "question": question,
                "baseline_router": routed,
            }
        else:
            gate = {
                "decision": routed["decision"],
                "reason": routed.get("reason"),
                "impact": impact,
                "baseline_router": routed,
            }
    elif arm == "memlineage_trust":
        routed = memlineage_baseline.gate_action(
            action,
            state,
            list(proposal.get("planner_context_memory_ids", [])),
        )
        gate = {
            "decision": routed["decision"],
            "reason": routed.get("reason"),
            "impact": impact,
            "baseline_router": routed,
        }
    elif impact.get("is_read_only"):
        gate = {"decision": "EXECUTE", "reason": "read_only", "impact": impact}
    else:
        shown_rationale = rationale if arm == "rationale_approval" else ""
        question = baseline_interactions.approval_prompt(action, shown_rationale)
        gate = {
            "decision": "ASK_PERMISSION",
            "reason": f"{arm}_review",
            "impact": impact,
            "question": question,
        }
    return {
        "arm": arm,
        "condition": arm,
        "memory_condition": "corrupted",
        "mitigation_enabled": False,
        "task": case["task"],
        "case_id": case["case_id"],
        "initial_action": action,
        "initial_rationale": rationale,
        "planner_context_memory_ids": proposal.get(
            "planner_context_memory_ids",
            sorted(memory_store.active_entries(
                state, scope=case.get("environment", {}).get("scope")
            )),
        ),
        "final_action": action,
        "initial_memory": copy.deepcopy(state),
        "final_memory": copy.deepcopy(state),
        "routing_decisions": [],
        "questions_asked": [],
        "human_interactions": [],
        "permission_interactions": [],
        "replan_count": 0,
        "approval_question": question,
        "residual_gate": gate,
        "safety_evaluation": safety_eval.evaluate(
            action, gate["decision"], case.get("safety", {})
        ),
    }


def _approval_continuation(case: Mapping[str, Any], arm: str):
    def factory(sandbox):
        def continue_after_observation(previous, observation, trajectory):
            state = previous.get("final_memory")
            proposal = planner.propose_action(
                case["task"],
                state,
                case_id=case["case_id"],
                stage_suffix=f"episode_step_{len(trajectory)}_{arm}",
                observation=observation,
                trajectory=trajectory,
                scope=case.get("environment", {}).get("scope"),
            )
            result = _approval_result(
                case,
                state,
                proposal,
                arm,
                trajectory=trajectory,
                stage_suffix=f"step_{len(trajectory)}",
            )
            result["replan_count"] = int(previous.get("replan_count", 0)) + 1
            return result

        return continue_after_observation

    return factory


def _generic_result(
    case: Mapping[str, Any],
    state: Mapping[str, Any],
    proposal: Mapping[str, Any],
    *,
    question_count: int,
    observation=None,
    trajectory=None,
) -> dict[str, Any]:
    proposal = copy.deepcopy(proposal)
    proposal["action"] = action_model.contextualize(proposal["action"], state)
    decision = baseline_interactions.generic_clarification_decision(
        case,
        state,
        proposal,
        question_count=question_count,
        observation=observation,
        trajectory=trajectory,
    )
    if decision["decision"] == "ASK" and question_count >= MAX_GENERIC_QUESTIONS:
        decision = {
            "decision": "REFUSE",
            "question": None,
            "reason": "generic_question_budget_exhausted",
        }
    if decision["decision"] == "EXECUTE":
        result = experimental_conditions.build_untreated_arm(
            case, "corrupted", proposal=proposal, state=state
        )
        result["arm"] = "generic_clarification"
        result["condition"] = "generic_clarification"
    else:
        gate_decision = "ASK_GENERIC" if decision["decision"] == "ASK" else "REFUSE"
        result = {
            "arm": "generic_clarification",
            "condition": "generic_clarification",
            "memory_condition": "corrupted",
            "mitigation_enabled": False,
            "task": case["task"],
            "case_id": case["case_id"],
            "initial_action": proposal["action"],
            "initial_rationale": proposal.get("rationale", ""),
            "planner_context_memory_ids": proposal.get(
                "planner_context_memory_ids", []
            ),
            "final_action": proposal["action"],
            "initial_memory": copy.deepcopy(state),
            "final_memory": copy.deepcopy(state),
            "routing_decisions": [],
            "questions_asked": [],
            "human_interactions": [],
            "permission_interactions": [],
            "replan_count": 0,
            "residual_gate": {
                "decision": gate_decision,
                "reason": decision.get("reason"),
                "question": decision.get("question"),
            },
            "safety_evaluation": safety_eval.evaluate(
                proposal["action"], gate_decision, case.get("safety", {})
            ),
        }
    result["generic_decision"] = decision
    result["generic_question_count"] = question_count
    result.setdefault("questions_asked", [])
    result.setdefault("human_interactions", [])
    result.setdefault("permission_interactions", [])
    result.setdefault("routing_decisions", [])
    return result


def _generic_continuation(case: Mapping[str, Any]):
    def factory(sandbox):
        def continue_after_observation(previous, observation, trajectory):
            state = previous.get("final_memory")
            proposal = planner.propose_action(
                case["task"],
                state,
                case_id=case["case_id"],
                stage_suffix=f"episode_step_{len(trajectory)}_generic_clarification",
                observation=observation,
                trajectory=trajectory,
                scope=case.get("environment", {}).get("scope"),
            )
            result = _generic_result(
                case,
                state,
                proposal,
                question_count=int(previous.get("generic_question_count", 0)),
                observation=observation,
                trajectory=trajectory,
            )
            result["replan_count"] = int(previous.get("replan_count", 0)) + 1
            return result

        return continue_after_observation

    return factory


class _GenericPreparedResultAgent:


    def __init__(
        self,
        result,
        continuation,
        allow_safe_report=False,
        *,
        ask_control="ASK_GENERIC",
        question_kind="generic_clarification",
        question_count_key="generic_question_count",
    ):
        self.result = result
        self.continuation = continuation
        self.allow_safe_report = allow_safe_report
        self.ask_control = ask_control
        self.question_kind = question_kind
        self.question_count_key = question_count_key
        self.plan_results = [result]
        self.emitted = False
        self.awaiting_generic = False
        self.awaiting_permission = False

    def _emit_current(self):
        self.emitted = True
        gate = self.result.get("residual_gate", {})
        decision = gate.get("decision", "REFUSE")
        action = self.result.get("final_action")
        if decision == "ASK_GENERIC":
            question = gate.get("question")
            self.awaiting_generic = True
            self.result.setdefault("questions_asked", []).append({
                "kind": self.question_kind,
                "question": question,
            })
            return {
                "type": "ASK_STATE",
                "question": question,
                "baseline_control": self.ask_control,
            }
        if decision == "ASK_PERMISSION" and action is not None:
            self.awaiting_permission = True
            return {
                "type": "ASK_PERMISSION",
                "action": action,
                "rationale": self.result.get("initial_rationale", ""),
                "question": gate.get("question"),
                "reason": gate.get("reason"),
            }
        if decision == "REFUSE":
            return {"type": "REFUSE", "reason": gate.get("reason", "baseline_refusal")}
        if decision == "EXECUTE" and action is not None:
            normalized = action_model.normalize(action)
            if (
                normalized["tool"] == "user"
                and normalized["operation"] == "report"
                and not self.allow_safe_report
            ):
                return {"type": "ABSTAIN", "reason": "planner_safe_report"}
            return {"type": "ACTION", "action": action}
        return {"type": "ABSTAIN", "reason": f"terminal_gate:{decision}"}

    def _continue(self, observation, trajectory):
        if self.continuation is None:
            return {"type": "ABSTAIN", "reason": "baseline_continuation_unavailable"}
        self.result = self.continuation(
            self.result,
            lightweight_runtime._public_observation(observation),
            lightweight_runtime._public_trajectory(trajectory),
        )
        self.plan_results.append(self.result)
        self.emitted = False
        return self._emit_current()

    def step(self, observation, trajectory):
        if self.awaiting_generic:
            self.awaiting_generic = False
            self.result[self.question_count_key] = int(
                self.result.get(self.question_count_key, 0)
            ) + 1
            self.result.setdefault("human_interactions", []).append({
                "kind": self.question_kind,
                "question": self.result.get("residual_gate", {}).get("question"),
                "answer": copy.deepcopy(observation),
                "memory_update": None,
            })
            return self._continue(observation, trajectory)
        if self.awaiting_permission:
            self.awaiting_permission = False
            allowed = bool((observation or {}).get("allowed")) or str(
                (observation or {}).get("permission", "")
            ).upper() == "ALLOW"
            self.result.setdefault("permission_interactions", []).append({
                "action": copy.deepcopy(self.result.get("final_action")),
                "answer": copy.deepcopy(observation),
            })
            if allowed:
                return {"type": "ACTION", "action": self.result.get("final_action")}
            return self._continue(observation, trajectory)
        if not self.emitted:
            return self._emit_current()
        oracle = (observation or {}).get("oracle", {})
        if oracle.get("task_completed") or oracle.get("acceptable_terminal"):
            return {
                "type": "DONE",
                "outcome": oracle.get("terminal_outcome") or "TASK_COMPLETED",
            }
        return self._continue(observation, trajectory)


def _run_untreated(
    case_path, case, arm, episode_root, initial_proposal, initial_state=None
):
    condition = arm
    state = _condition_state(case, condition, initial_state)
    return lightweight_runtime._execute_result(
        case,
        episode_root=episode_root,
        result_factory=lambda sandbox: experimental_conditions.build_untreated_arm(
            case,
            condition,
            proposal=copy.deepcopy(initial_proposal)
            if initial_proposal is not None
            else build_proposal(case, condition, state),
            state=state,
        ),
        continuation_factory=_untreated_continuation(case, condition),
    )


def _run_approval(
    case_path, case, arm, episode_root, initial_proposal, initial_state=None
):
    state = _condition_state(case, "corrupted", initial_state)
    mode = {
        "bare_approval": "bare",
        "rationale_approval": "rationale",
        "safety_sentry": "safety_sentry",
        "memlineage_trust": "bare",
        "auto_execute": "bare",
    }[arm]
    return lightweight_runtime._execute_result(
        case,
        episode_root=episode_root,
        result_factory=lambda sandbox: _approval_result(
            case, state, copy.deepcopy(initial_proposal), arm
        ),
        continuation_factory=_approval_continuation(case, arm),
        permission_channel=baseline_interactions.ApprovalSimulator(case, mode),
    )


def _oracle_ground_truths(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    truths = case.get("ground_truth_states")
    if isinstance(truths, list) and truths:
        return [copy.deepcopy(item) for item in truths if isinstance(item, Mapping)]
    truth = case.get("ground_truth_state")
    return [copy.deepcopy(truth)] if isinstance(truth, Mapping) else []


def _repair_oracle_state(
    case: Mapping[str, Any],
    corrupted_state: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:

    state = copy.deepcopy(corrupted_state)
    case_scope = case.get("environment", {}).get("scope")
    support_by_key: dict[str, list[str]] = {}
    for support in case.get("oracle_support_states", []):
        memory_id = support.get("memory_id")
        entry = state.get(memory_id, {})
        key = entry.get("key")
        if key:
            support_by_key.setdefault(key, []).append(memory_id)

    repairs = []
    for truth in _oracle_ground_truths(case):
        key = truth.get("key")
        if not key or "value" not in truth:
            continue
        scope = truth.get("scope") or case_scope or dict(memory_store.DEFAULT_SCOPE)
        support_ids = set(support_by_key.get(key, []))
        active_truth = next(
            (
                entry
                for entry in memory_store.active_entries(state, scope=scope).values()
                if entry.get("key") == key and entry.get("value") == truth["value"]
            ),
            None,
        )
        if active_truth is not None and support_ids:
            ancestors = set(active_truth.get("supersedes", []))
            frontier = list(ancestors)
            while frontier:
                ancestor_id = frontier.pop()
                ancestor = state.get(ancestor_id, {})
                for parent_id in ancestor.get("supersedes", []):
                    if parent_id not in ancestors:
                        ancestors.add(parent_id)
                        frontier.append(parent_id)
            if support_ids.issubset(ancestors):
                continue
        applicable_old_ids = [
            entry_id
            for entry_id, entry in memory_store.active_entries(state).items()
            if entry.get("key") == key
            and memory_store.scope_matches(entry.get("scope"), scope)
        ]
        primary_id = next(iter(support_by_key.get(key, [])), None)
        new_id = memory_repair.repair(
            state,
            key=key,
            value=truth["value"],
            source="oracle_ground_truth",
            confidence="oracle",
            evidence={
                "baseline": "oracle_statewise",
                "oracle_support_memory_ids": support_by_key.get(key, []),
            },
            scope=scope,
            supersede_id=primary_id,
        )


        for entry_id in applicable_old_ids:
            if entry_id in state:
                state[entry_id]["status"] = "deprecated"
        state[new_id]["supersedes"] = sorted(set(
            state[new_id].get("supersedes", []) + applicable_old_ids
        ))
        repairs.append({
            "key": key,
            "value": truth["value"],
            "scope": scope,
            "new_memory_id": new_id,
            "superseded_memory_ids": sorted(applicable_old_ids),
            "oracle_support_memory_ids": sorted(support_by_key.get(key, [])),
        })
    return state, repairs


def _oracle_result(
    case_path, case, sandbox, initial_proposal, initial_state=None
):
    corrupted_state = _condition_state(case, "corrupted", initial_state)
    repaired_state, repairs = _repair_oracle_state(case, corrupted_state)
    replanned = planner.propose_action(
        case["task"],
        repaired_state,
        case_id=case["case_id"],
        stage_suffix="replan_final_correct",
        scope=case.get("environment", {}).get("scope"),
    )
    result = lightweight_runtime.main_loop.run_case(
        case_path,
        condition="correct",
        support_track="automatic",
        counterfactual_track="automatic",
        initial_state=repaired_state,
        initial_proposal=replanned,
        verification_context=sandbox.verification_context(),
    )
    initial_action = action_model.contextualize(
        copy.deepcopy(initial_proposal["action"]), corrupted_state
    )
    oracle_round = {
        "cycle": "oracle_pre_replan",
        "support_states": copy.deepcopy(case.get("oracle_support_states", [])),
        "critical_states": [
            item.get("id") for item in case.get("oracle_support_states", [])
        ],
        "routing_decisions": [
            {
                "method": "ORACLE_REPAIR",
                "key": repair["key"],
                "memory_id": next(iter(repair["oracle_support_memory_ids"]), None),
                "verified_value": repair["value"],
                "reason": "oracle_support_state_is_decision_critical",
            }
            for repair in repairs
        ],
        "repairs": copy.deepcopy(repairs),
    }
    result.update({
        "arm": "oracle_statewise",
        "condition": "oracle_statewise",
        "memory_condition": "corrupted",
        "mitigation_enabled": True,
        "oracle_assisted": True,
        "oracle_adapter": {
            "contract": "direct_decision_critical_state_truth_before_replan",
            "repairs": copy.deepcopy(repairs),
        },
        "initial_action": initial_action,
        "initial_rationale": initial_proposal.get("rationale", ""),
        "planner_context_memory_ids": list(
            initial_proposal.get("planner_context_memory_ids", [])
        ),
        "initial_memory": copy.deepcopy(corrupted_state),
        "initial_impact": interceptor.classify(initial_action),
        "support_states": copy.deepcopy(case.get("oracle_support_states", [])),
        "annotated_states": [
            {**copy.deepcopy(item), "decision_critical": True, "oracle": True}
            for item in case.get("oracle_support_states", [])
        ],
        "critical_states": [
            item.get("id") for item in case.get("oracle_support_states", [])
        ],
        "inspection_rounds": [oracle_round] + list(result.get("inspection_rounds", [])),
        "routing_decisions": oracle_round["routing_decisions"]
        + list(result.get("routing_decisions", [])),
        "replan_count": int(result.get("replan_count", 0)) + 1,
    })
    return result


def _oracle_continuation(case_path, case):
    def factory(sandbox):
        def continue_after_observation(previous, observation, trajectory):
            return lightweight_runtime.main_loop.run_case(
                case_path,
                condition="correct",
                initial_state=previous.get("final_memory"),
                initial_observation=observation,
                trajectory=trajectory,


                initial_stage_suffix="episode_step_1_correct",
                verification_context=sandbox.verification_context(),
            )
        return continue_after_observation
    return factory


def _run_oracle(
    case_path, case, episode_root, initial_proposal, initial_state=None
):
    return lightweight_runtime._execute_result(
        case,
        episode_root=episode_root,
        result_factory=lambda sandbox: _oracle_result(
            case_path,
            case,
            sandbox,
            copy.deepcopy(initial_proposal),
            initial_state=initial_state,
        ),
        continuation_factory=_oracle_continuation(case_path, case),
    )


def _run_generic(
    case_path, case, episode_root, initial_proposal, initial_state=None
):
    state = _condition_state(case, "corrupted", initial_state)
    return lightweight_runtime._execute_result(
        case,
        episode_root=episode_root,
        result_factory=lambda sandbox: _generic_result(
            case,
            state,
            copy.deepcopy(initial_proposal),
            question_count=0,
        ),
        continuation_factory=_generic_continuation(case),
        agent_factory=lambda result, continuation, allow_safe_report: _GenericPreparedResultAgent(
            result, continuation, allow_safe_report
        ),
        user_channel=baseline_interactions.GenericUserSimulator(case),
        permission_channel=baseline_interactions.ApprovalSimulator(case, "bare"),
    )


def _ask_or_assume_result(
    case: Mapping[str, Any],
    state: Mapping[str, Any],
    proposal: Mapping[str, Any],
    *,
    question_count: int,
    observation=None,
    trajectory=None,
) -> dict[str, Any]:
    proposal = copy.deepcopy(proposal)
    proposal["action"] = action_model.contextualize(proposal["action"], state)
    decision = ask_or_assume_baseline.decide(
        case,
        proposal,
        question_count=question_count,
        observation=observation,
        trajectory=trajectory,
    )
    if decision["decision"] == "ASK" and question_count >= MAX_GENERIC_QUESTIONS:
        decision = {
            "decision": "REFUSE",
            "question": None,
            "reason": "ask_or_assume_question_budget_exhausted",
        }
    if decision["decision"] == "EXECUTE":
        result = experimental_conditions.build_untreated_arm(
            case, "corrupted", proposal=proposal, state=state
        )
        result["arm"] = "ask_or_assume"
        result["condition"] = "ask_or_assume"
    else:
        gate_decision = "ASK_GENERIC" if decision["decision"] == "ASK" else "REFUSE"
        result = {
            "arm": "ask_or_assume",
            "condition": "ask_or_assume",
            "memory_condition": "corrupted",
            "mitigation_enabled": False,
            "task": case["task"],
            "case_id": case["case_id"],
            "initial_action": proposal["action"],
            "initial_rationale": proposal.get("rationale", ""),
            "planner_context_memory_ids": proposal.get("planner_context_memory_ids", []),
            "final_action": proposal["action"],
            "initial_memory": copy.deepcopy(state),
            "final_memory": copy.deepcopy(state),
            "routing_decisions": [],
            "questions_asked": [],
            "human_interactions": [],
            "permission_interactions": [],
            "replan_count": 0,
            "residual_gate": {
                "decision": gate_decision,
                "reason": decision.get("reason"),
                "question": decision.get("question"),
            },
            "safety_evaluation": safety_eval.evaluate(
                proposal["action"], gate_decision, case.get("safety", {})
            ),
        }
    result["ask_or_assume_decision"] = decision
    result["ask_or_assume_question_count"] = question_count
    result.setdefault("questions_asked", [])
    result.setdefault("human_interactions", [])
    result.setdefault("permission_interactions", [])
    result.setdefault("routing_decisions", [])
    return result


def _ask_or_assume_continuation(case: Mapping[str, Any]):
    def factory(sandbox):
        def continue_after_observation(previous, observation, trajectory):
            state = previous.get("final_memory")
            proposal = planner.propose_action(
                case["task"],
                state,
                case_id=case["case_id"],
                stage_suffix=f"episode_step_{len(trajectory)}_ask_or_assume",
                observation=observation,
                trajectory=trajectory,
                scope=case.get("environment", {}).get("scope"),
            )
            result = _ask_or_assume_result(
                case,
                state,
                proposal,
                question_count=int(previous.get("ask_or_assume_question_count", 0)),
                observation=observation,
                trajectory=trajectory,
            )
            result["replan_count"] = int(previous.get("replan_count", 0)) + 1
            return result

        return continue_after_observation

    return factory


def _run_ask_or_assume(
    case_path, case, episode_root, initial_proposal, initial_state=None
):
    state = _condition_state(case, "corrupted", initial_state)
    return lightweight_runtime._execute_result(
        case,
        episode_root=episode_root,
        result_factory=lambda sandbox: _ask_or_assume_result(
            case,
            state,
            copy.deepcopy(initial_proposal),
            question_count=0,
        ),
        continuation_factory=_ask_or_assume_continuation(case),
        agent_factory=lambda result, continuation, allow_safe_report: _GenericPreparedResultAgent(
            result,
            continuation,
            allow_safe_report,
            ask_control="ASK_TASK_UNCERTAINTY",
            question_kind="task_uncertainty",
            question_count_key="ask_or_assume_question_count",
        ),
        user_channel=baseline_interactions.GenericUserSimulator(case),
        permission_channel=baseline_interactions.ApprovalSimulator(case, "bare"),
    )


def run_executable_arm(
    case_path: str,
    arm: str,
    *,
    episode_root=None,
    initial_proposal: Mapping[str, Any] | None = None,
    initial_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    definition = arm_definition(arm)
    case = lightweight_runtime.main_loop.load_case(case_path)
    if uses_shared_corrupted_proposal(arm) and initial_proposal is None:
        initial_proposal = build_proposal(
            case, "corrupted", initial_state=initial_state
        )
    if arm in {"correct", "corrupted", "no_memory"}:
        return _run_untreated(
            case_path, case, arm, episode_root, initial_proposal, initial_state
        )
    if arm in {
        "auto_execute",
        "bare_approval",
        "rationale_approval",
        "safety_sentry",
        "memlineage_trust",
    }:
        return _run_approval(
            case_path, case, arm, episode_root, initial_proposal, initial_state
        )
    if arm == "live_refresh":
        state = _condition_state(case, "corrupted", initial_state)
        proposal = copy.deepcopy(initial_proposal)
        return lightweight_runtime._execute_result(
            case,
            episode_root=episode_root,
            result_factory=lambda sandbox: live_refresh_baseline.initial_result(
                case, state, proposal
            ),
            continuation_factory=live_refresh_baseline.continuation(case),
        )
    if arm == "critic_tool_grounded":
        state = _condition_state(case, "corrupted", initial_state)
        proposal = copy.deepcopy(initial_proposal)
        return lightweight_runtime._execute_result(
            case,
            episode_root=episode_root,
            result_factory=lambda sandbox: critic_tool_grounded_baseline.build_result(
                case, state, proposal, sandbox
            ),
            continuation_factory=critic_tool_grounded_baseline.continuation(case),
        )
    if arm == "generic_clarification":
        return _run_generic(
            case_path, case, episode_root, initial_proposal, initial_state
        )
    if arm == "ask_or_assume":
        return _run_ask_or_assume(
            case_path, case, episode_root, initial_proposal, initial_state
        )
    if arm == "statewise_v1":
        with targeted_variants.use_variant("combined"):
            return lightweight_runtime.run_executable_case(
                case_path,
                condition="corrupted",
                episode_root=episode_root,
                initial_proposal=copy.deepcopy(initial_proposal),
                initial_state=copy.deepcopy(initial_state),
            )
    if arm == "statewise_v2_retrieval":


        with attribution_v2.use_variant("retrieval"):
            with targeted_variants.use_variant("combined"):
                return lightweight_runtime.run_executable_case(
                    case_path,
                    condition="corrupted",
                    episode_root=episode_root,
                    initial_proposal=copy.deepcopy(initial_proposal),
                    initial_state=copy.deepcopy(initial_state),
                )
    if arm in {"v1_no_attribution", "v1_no_repair", "v1_no_counterfactual"}:
        variant = {
            "v1_no_attribution": "no_attribution",
            "v1_no_repair": "no_repair",
            "v1_no_counterfactual": "no_counterfactual",
        }[arm]
        with targeted_variants.use_variant(variant):
            return lightweight_runtime.run_executable_case(
                case_path,
                condition="corrupted",
                episode_root=episode_root,
                initial_proposal=copy.deepcopy(initial_proposal),
                initial_state=copy.deepcopy(initial_state),
            )
    if arm == "oracle_statewise":
        with targeted_variants.use_variant("combined"):
            return _run_oracle(
                case_path,
                case,
                episode_root,
                copy.deepcopy(initial_proposal),
                initial_state,
            )
    raise AssertionError(f"unhandled implemented arm: {definition.name}")


def summarize_result(
    case: Mapping[str, Any], arm: str, result: Mapping[str, Any]
) -> dict[str, Any]:
    runtime = result.get("runtime_execution", {})
    oracle = runtime.get("oracle", {})
    trajectory = runtime.get("trajectory", [])
    control_counts: dict[str, int] = {}
    for event in trajectory:
        if not isinstance(event, Mapping):
            continue
        kind = str(event.get("type", "UNKNOWN"))
        control_counts[kind] = control_counts.get(kind, 0) + 1
    initial_memory = result.get("initial_memory", {})
    final_memory = result.get("final_memory", {})
    initial_active = {
        key: value
        for key, value in (initial_memory or {}).items()
        if isinstance(value, Mapping) and value.get("status") == "active"
    }
    final_active = {
        key: value
        for key, value in (final_memory or {}).items()
        if isinstance(value, Mapping) and value.get("status") == "active"
    }
    residual_gate = result.get("residual_gate", {}) or {}
    baseline_router = residual_gate.get("baseline_router", {}) or {}
    untrusted_ids = list(
        baseline_router.get("untrusted_justification_ids", []) or []
    )
    oracle_adapter = result.get("oracle_adapter", {}) or {}
    task_success = bool(oracle.get("task_completed"))
    safety_violation = bool(oracle.get("violated"))
    permission_interactions = max(
        len(result.get("permission_interactions", [])),
        control_counts.get("ASK_PERMISSION", 0),
    )

    attribution_precision = None
    attribution_recall = None
    if arm == "oracle_statewise" and case.get("oracle_support_states"):


        attribution_precision = 1.0
        attribution_recall = 1.0
    elif arm in {"statewise_v1", "statewise_v2_retrieval"}:
        attribution = (
            result.get("episode_attribution_metrics")
            or result.get("attribution_metrics", {})
            or {}
        )
        if attribution.get("precision") is not None:
            attribution_precision = float(attribution["precision"])
        if attribution.get("recall") is not None:
            attribution_recall = float(attribution["recall"])

    truth_by_key = {
        truth.get("key"): truth
        for truth in _oracle_ground_truths(case)
        if truth.get("key") and "value" in truth
    }
    repair_events = []
    for repair in oracle_adapter.get("repairs", []) or []:
        if isinstance(repair, Mapping) and repair.get("key"):
            repair_events.append((repair.get("key"), repair.get("value")))
    for decision in result.get("routing_decisions", []) or []:
        if (
            isinstance(decision, Mapping)
            and decision.get("method") == "VERIFY_STATE"
            and decision.get("key")
            and "verified_value" in decision
        ):
            repair_events.append((decision.get("key"), decision.get("verified_value")))
    for interaction in result.get("human_interactions", []) or []:
        if not isinstance(interaction, Mapping):
            continue
        update = interaction.get("memory_update")
        if isinstance(update, Mapping) and interaction.get("state_key"):
            repair_events.append((interaction.get("state_key"), update.get("value")))

    final_state = result.get("final_memory", {}) or {}
    correct_repair_events = 0
    for key, value in repair_events:
        truth = truth_by_key.get(key)
        scope = (truth or {}).get("scope") or case.get("environment", {}).get("scope")
        serving = memory_store.find_by_key(final_state, key, scope=scope)
        if (
            truth is not None
            and value == truth.get("value")
            and serving is not None
            and serving.get("value") == truth.get("value")
        ):
            correct_repair_events += 1
    repair_performed = bool(repair_events)
    repair_correct = (
        correct_repair_events == len(repair_events) if repair_performed else None
    )
    return {
        "case_id": case.get("case_id"),
        "arm": arm,
        "md_id": ARM_REGISTRY[arm].md_id,
        "status": runtime.get("episode_status"),
        "terminal_reason": runtime.get("terminal_reason"),
        "task_success": task_success,
        "risk_adjusted_task_success": task_success and not safety_violation,
        "acceptable_safe_terminal": bool(oracle.get("acceptable_terminal")),
        "safety_violation": safety_violation,
        "steps": int(runtime.get("steps") or 0),
        "control_counts": control_counts,
        "questions": len(result.get("questions_asked", [])),
        "human_interactions": len(result.get("human_interactions", [])),
        "permission_interactions": permission_interactions,
        "residual_permission_required": permission_interactions > 0,
        "replan_count": int(result.get("replan_count") or 0),
        "memory_changed": initial_active != final_active,
        "baseline_decision": (
            baseline_router.get("raw_decision")
            or baseline_router.get("decision")
            or residual_gate.get("decision")
        ),
        "baseline_reason": baseline_router.get("reason") or residual_gate.get("reason"),
        "untrusted_justification_ids": untrusted_ids,
        "lineage_blocked": bool(untrusted_ids),
        "oracle_repair_count": len(oracle_adapter.get("repairs", []) or []),
        "attribution_precision": attribution_precision,
        "attribution_recall": attribution_recall,
        "repair_performed": repair_performed,
        "repair_correct": repair_correct,
        "repair_event_count": len(repair_events),
        "repair_correct_event_count": correct_repair_events,
        "unnecessary_mutation": oracle.get("unnecessary_mutation", {}),
        "capability_score_eligible": case.get("capability_score_eligible") is not False,
        "initial_action": result.get("initial_action"),
        "final_action": result.get("final_action"),
    }
