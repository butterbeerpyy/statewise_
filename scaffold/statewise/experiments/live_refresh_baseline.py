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
    actions: list[dict[str, Any]] = []
    for path in (fixture.get("files", {}) or {}):
        actions.append({
            "tool": "filesystem",
            "operation": "read",
            "arguments": {"path": path},
            "target": None,
        })
    if (fixture.get("git", {}) or {}).get("init"):
        actions.append({
            "tool": "git",
            "operation": "status",
            "arguments": {},
            "target": None,
        })


    if not actions:
        actions.append({
            "tool": "filesystem",
            "operation": "list",
            "arguments": {"path": "."},
            "target": None,
        })
    return actions


def _step_result(
    case: Mapping[str, Any],
    state: Mapping[str, Any],
    action: Mapping[str, Any],
    *,
    initial_proposal: Mapping[str, Any],
    refresh_index: int,
    refresh_observations: list[Mapping[str, Any]],
    final: bool = False,
) -> dict[str, Any]:
    action = action_model.normalize(copy.deepcopy(action))
    gate = {"decision": "EXECUTE", "reason": "live_refresh_observation"}
    return {
        "arm": "live_refresh",
        "condition": "live_refresh",
        "memory_condition": "corrupted",
        "mitigation_enabled": False,
        "task": case["task"],
        "case_id": case["case_id"],
        "initial_action": copy.deepcopy(initial_proposal.get("action")),
        "initial_rationale": initial_proposal.get("rationale", ""),
        "planner_context_memory_ids": list(
            initial_proposal.get(
                "planner_context_memory_ids",
                sorted(memory_store.active_entries(state)),
            )
        ),
        "initial_memory": copy.deepcopy(state),
        "final_memory": copy.deepcopy(state),
        "final_action": action,
        "initial_impact": {"is_read_only": True} if not final else None,
        "routing_decisions": [],
        "questions_asked": [],
        "human_interactions": [],
        "permission_interactions": [],
        "replan_count": 0 if not final else 1,
        "residual_gate": gate,
        "safety_evaluation": safety_eval.evaluate(
            action, gate["decision"], case.get("safety", {})
        ),
        "live_refresh": {
            "refresh_index": refresh_index,
            "refresh_actions": _refresh_actions(case),
            "refresh_observations": copy.deepcopy(refresh_observations),
            "repair_performed": False,
            "clarification_performed": False,
        },
    }


def initial_result(
    case: Mapping[str, Any],
    state: Mapping[str, Any],
    initial_proposal: Mapping[str, Any],
) -> dict[str, Any]:
    actions = _refresh_actions(case)
    return _step_result(
        case,
        state,
        actions[0],
        initial_proposal=initial_proposal,
        refresh_index=0,
        refresh_observations=[],
    )


def continuation(case: Mapping[str, Any]):
    actions = _refresh_actions(case)

    def factory(sandbox):
        def continue_after_observation(previous, observation, trajectory):
            state = copy.deepcopy(previous.get("final_memory", {}))
            info = copy.deepcopy(previous.get("live_refresh", {}))
            observations = list(info.get("refresh_observations", []))
            observations.append(copy.deepcopy(observation or {}))
            index = int(info.get("refresh_index", 0))
            initial_proposal = {
                "action": previous.get("initial_action"),
                "rationale": previous.get("initial_rationale", ""),
                "planner_context_memory_ids": previous.get(
                    "planner_context_memory_ids", []
                ),
            }
            next_index = index + 1
            if next_index < len(actions):
                return _step_result(
                    case,
                    state,
                    actions[next_index],
                    initial_proposal=initial_proposal,
                    refresh_index=next_index,
                    refresh_observations=observations,
                )

            refreshed_observation = {
                "refresh_type": "machine_observable_state",
                "observations": observations,
            }
            proposal = planner.propose_action(
                case["task"],
                state,
                case_id=case["case_id"],
                stage_suffix="live_refresh_replan",
                observation=refreshed_observation,
                trajectory=trajectory,
                scope=case.get("environment", {}).get("scope"),
            )


            action = action_model.normalize(copy.deepcopy(proposal.get("action")))
            schema_errors = action_model.validate(action)
            if schema_errors:
                gate = {
                    "decision": "REFUSE",
                    "reason": "invalid_action_schema",
                    "schema_errors": schema_errors,
                }
            else:
                gate = residual_risk.gate(
                    action, rationale=proposal.get("rationale", "")
                )
            result = {
                "arm": "live_refresh",
                "condition": "live_refresh",
                "memory_condition": "corrupted",
                "mitigation_enabled": False,
                "task": case["task"],
                "case_id": case["case_id"],
                "initial_action": previous.get("initial_action"),
                "initial_rationale": previous.get("initial_rationale", ""),
                "planner_context_memory_ids": previous.get(
                    "planner_context_memory_ids", []
                ),
                "initial_memory": copy.deepcopy(
                    previous.get("initial_memory", state)
                ),
                "final_memory": copy.deepcopy(state),
                "final_action": action,
                "routing_decisions": [],
                "questions_asked": [],
                "human_interactions": [],
                "permission_interactions": [],
                "replan_count": 1,
                "residual_gate": gate,
                "safety_evaluation": safety_eval.evaluate(
                    action, gate["decision"], case.get("safety", {})
                ),
            }
            result["live_refresh"] = {
                "refresh_index": next_index,
                "refresh_actions": actions,
                "refresh_observations": observations,
                "repair_performed": False,
                "clarification_performed": False,
                "final_replan_observation": refreshed_observation,
            }
            return result

        return continue_after_observation

    return factory
