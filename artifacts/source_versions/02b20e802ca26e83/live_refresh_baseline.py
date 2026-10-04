from __future__ import annotations

import copy
from typing import Any, Mapping

from scaffold.statewise.agents import planner
from scaffold.statewise.core import action_model, residual_risk
from scaffold.statewise.evaluation import safety_eval
from scaffold.statewise.memory import memory_store


def _refresh_actions(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    execution = case.get("execution", {})
    fixture = execution.get("fixture", {})
    actions = [
        {"tool": "filesystem", "operation": "read", "arguments": {"path": path}, "target": None}
        for path in (fixture.get("files", {}) or {})
    ]
    if (fixture.get("git", {}) or {}).get("init"):
        actions.append({"tool": "git", "operation": "status", "arguments": {}, "target": None})
    for verifier in execution.get("state_verifiers", []) or []:
        fixture_name = verifier.get("fixture") if isinstance(verifier, Mapping) else None
        if fixture_name:
            actions.append({
                "tool": "filesystem", "operation": "read",
                "arguments": {"path": f".statewise/verification/{fixture_name}"},
                "target": None,
            })
    environments = (fixture.get("python_environments", {}) or {})
    packages = sorted({
        package
        for environment in environments.values()
        for package in (environment.get("packages", []) or [])
    })
    for environment in sorted(environments):
        for package in packages:
            actions.append({
                "tool": "environment", "operation": "inspect_package",
                "arguments": {"package": package, "environment": environment},
                "target": environment,
            })
    if not actions:
        actions.append({"tool": "filesystem", "operation": "list", "arguments": {"path": "."}, "target": None})
    return actions


def _refresh_step(
    case, state, action, initial_proposal, index, observations, *,
    arm="live_refresh", memory_condition="corrupted",
):
    action = action_model.normalize(copy.deepcopy(action))
    gate = {"decision": "EXECUTE", "reason": "live_refresh_observation"}
    return {
        "arm": arm, "condition": arm, "memory_condition": memory_condition,
        "mitigation_enabled": False, "task": case["task"], "case_id": case["case_id"],
        "initial_action": copy.deepcopy(initial_proposal.get("action")),
        "initial_rationale": initial_proposal.get("rationale", ""),
        "planner_context_memory_ids": list(initial_proposal.get("planner_context_memory_ids", sorted(memory_store.active_entries(state)))),
        "initial_memory": copy.deepcopy(state), "final_memory": copy.deepcopy(state),
        "final_action": action, "initial_impact": {"is_read_only": True},
        "routing_decisions": [], "questions_asked": [], "human_interactions": [],
        "permission_interactions": [], "replan_count": 0, "residual_gate": gate,
        "safety_evaluation": safety_eval.evaluate(action, gate["decision"], case.get("safety", {})),
        "live_refresh": {"refresh_index": index, "refresh_actions": _refresh_actions(case),
                          "refresh_observations": copy.deepcopy(observations),
                          "repair_performed": False, "clarification_performed": False},
    }


def initial_result(
    case, state, initial_proposal, sandbox, *,
    arm="live_refresh", memory_condition="corrupted"
):


    actions = _refresh_actions(case)
    observations = []
    for action in actions:
        try:
            observations.append({"action": copy.deepcopy(action),
                                 "action_result": sandbox.execute(action)})
        except Exception as exc:
            observations.append({
                "action": copy.deepcopy(action),
                "runtime_error": {"type": type(exc).__name__, "message": str(exc)},
                "ok": False,
            })
    refreshed = {"refresh_type": "machine_observable_state",
                 "observations": observations}
    proposal = planner.propose_action(
        case["task"], state, case_id=case["case_id"],
        stage_suffix="live_refresh_replan", observation=refreshed,
        trajectory=[], scope=case.get("environment", {}).get("scope"),
    )
    action = action_model.normalize(copy.deepcopy(proposal.get("action")))
    errors = action_model.validate(action)
    gate = ({"decision": "REFUSE", "reason": "invalid_action_schema",
             "schema_errors": errors} if errors else
            residual_risk.gate(action, rationale=proposal.get("rationale", "")))
    return {
        "arm": arm, "condition": arm, "memory_condition": memory_condition,
        "mitigation_enabled": False, "task": case["task"], "case_id": case["case_id"],
        "initial_action": copy.deepcopy(initial_proposal.get("action")),
        "initial_rationale": initial_proposal.get("rationale", ""),
        "planner_context_memory_ids": initial_proposal.get("planner_context_memory_ids", []),
        "initial_memory": copy.deepcopy(state), "final_memory": copy.deepcopy(state),
        "final_action": action, "routing_decisions": [], "questions_asked": [],
        "human_interactions": [], "permission_interactions": [], "replan_count": 1,
        "residual_gate": gate,
        "safety_evaluation": safety_eval.evaluate(action, gate["decision"], case.get("safety", {})),
        "live_refresh": {
            "refresh_index": len(actions) - 1, "refresh_actions": actions,
            "refresh_observations": observations, "repair_performed": False,
            "clarification_performed": False, "final_replan_observation": refreshed,
            "action_budget_cost": 0, "action_budget_limit": 8,
        },
    }


def continuation(case, *, arm="live_refresh", memory_condition="corrupted"):
    actions = _refresh_actions(case)

    def factory(sandbox):
        def continue_after_observation(previous, observation, trajectory):
            state = copy.deepcopy(previous.get("final_memory", {}))
            info = previous.get("live_refresh", {})
            observations = list(info.get("refresh_observations", []))
            observations.append(copy.deepcopy(observation or {}))
            index = int(info.get("refresh_index", 0)) + 1
            initial_proposal = {
                "action": previous.get("initial_action"),
                "rationale": previous.get("initial_rationale", ""),
                "planner_context_memory_ids": previous.get("planner_context_memory_ids", []),
            }
            if index < len(actions):
                return _refresh_step(
                    case, state, actions[index], initial_proposal, index, observations,
                    arm=arm, memory_condition=memory_condition,
                )
            refreshed = {"refresh_type": "machine_observable_state", "observations": observations}
            proposal = planner.propose_action(
                case["task"], state, case_id=case["case_id"], stage_suffix="live_refresh_replan",
                observation=refreshed, trajectory=trajectory,
                scope=case.get("environment", {}).get("scope"),
            )
            action = action_model.normalize(copy.deepcopy(proposal.get("action")))
            errors = action_model.validate(action)
            gate = {"decision": "REFUSE", "reason": "invalid_action_schema", "schema_errors": errors} if errors else residual_risk.gate(action, rationale=proposal.get("rationale", ""))
            return {
                "arm": arm, "condition": arm, "memory_condition": memory_condition,
                "mitigation_enabled": False, "task": case["task"], "case_id": case["case_id"],
                "initial_action": previous.get("initial_action"), "initial_rationale": previous.get("initial_rationale", ""),
                "planner_context_memory_ids": previous.get("planner_context_memory_ids", []),
                "initial_memory": copy.deepcopy(previous.get("initial_memory", state)),
                "final_memory": copy.deepcopy(state), "final_action": action,
                "routing_decisions": [], "questions_asked": [], "human_interactions": [],
                "permission_interactions": [], "replan_count": 1, "residual_gate": gate,
                "safety_evaluation": safety_eval.evaluate(action, gate["decision"], case.get("safety", {})),
                "live_refresh": {"refresh_index": index, "refresh_actions": actions,
                                  "refresh_observations": observations, "repair_performed": False,
                                  "clarification_performed": False, "final_replan_observation": refreshed},
            }
        return continue_after_observation
    return factory
