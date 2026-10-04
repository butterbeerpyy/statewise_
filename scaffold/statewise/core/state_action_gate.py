from __future__ import annotations

from scaffold.statewise.core import action_model
from scaffold.statewise.core import reliability
from scaffold.statewise.evaluation import measurement
from scaffold.statewise.memory import memory_store


RELIABILITY_THRESHOLD = 0.6


def _subset(expected, actual):
    return measurement.semantic_subset(expected, actual)


def _action_matches(action, pattern):
    if action is None or not pattern:
        return False
    return _subset(action_model.normalize(pattern), action_model.normalize(action))


def _binding_entry_is_trusted(entry, state, scope=None):

    if not entry.get("source"):
        return True
    scored = reliability.score(entry, state, current_scope=scope)
    return scored["reliability"] >= RELIABILITY_THRESHOLD


def gate(action, state, safety, scope=None):

    effective_action = action_model.normalize(action)
    binding_rewrites = []
    for binding in safety.get("action_state_bindings", []):
        tools = binding.get("tools", [])
        operations = binding.get("operations", [])
        if tools and effective_action.get("tool") not in tools:
            continue
        if operations and effective_action.get("operation") not in operations:
            continue
        state_key = binding.get("state_key")
        entry = memory_store.find_by_key(state, state_key, scope=scope)
        if entry is None or entry.get("value") is None:
            continue
        if not _binding_entry_is_trusted(entry, state, scope=scope):
            return {
                "decision": "REFUSE",
                "reason": "unreliable_state_binding",
                "state_key": state_key,
                "state_value": entry.get("value"),
                "memory_id": entry.get("id"),
                "safe_fallback": "ABSTAIN",
            }
        state_value = entry["value"]
        before = action_model.normalize(effective_action)
        if binding.get("bind_target", True):
            effective_action["target"] = state_value
        argument = binding.get("argument")
        if argument:
            effective_action["arguments"][argument] = state_value
        if not action_model.equivalent(before, effective_action):
            binding_rewrites.append({
                "binding_id": binding.get("id"),
                "state_key": state_key,
                "state_value": state_value,
                "before": before,
                "after": action_model.normalize(effective_action),
            })

    for constraint in safety.get("state_action_constraints", []):
        state_pattern = constraint.get("when_state", {})
        entry = memory_store.find_by_key(
            state, state_pattern.get("key"), scope=scope
        )
        if entry is None or entry.get("value") != state_pattern.get("equals"):
            continue
        if not _action_matches(effective_action, constraint.get("action", {})):
            continue
        decision = constraint.get("decision", "REFUSE")
        result = {
            "decision": decision,
            "reason": constraint.get("reason", "state_action_constraint"),
            "constraint_id": constraint.get("id"),
            "state_key": state_pattern.get("key"),
            "state_value": entry.get("value"),
            "action": action_model.normalize(effective_action),
        }
        if binding_rewrites:
            result["state_binding_rewrites"] = binding_rewrites
        if decision == "REWRITE":
            result["rewrite_action"] = action_model.normalize(
                constraint.get("rewrite_action", {})
            )
        return result
    if binding_rewrites:
        return {
            "decision": "REWRITE",
            "reason": "action_bound_to_resolved_state",
            "rewrite_action": action_model.normalize(effective_action),
            "state_binding_rewrites": binding_rewrites,
        }
    return {"decision": "CONTINUE", "reason": "no_state_action_constraint"}
