from scaffold.statewise.core import reliability
from scaffold.statewise.runtime import tools


RELIABILITY_THRESHOLD = 0.6
RESOLVED_VERIFICATION_STATUSES = {"CONFIRMED", "REFUTED"}


def route(
    critical_states,
    state,
    action_impact,
    case=None,
    human_authoritative_keys=None,
    verification_context=None,
):

    human_authoritative_keys = set(human_authoritative_keys or ())
    case = case or {}
    decisions = []


    if action_impact.get("violates_hard_policy"):
        for critical_state in critical_states:
            decisions.append({
                "state_id": critical_state["id"],
                "method": "REFUSE",
                "reason": "hard_policy_violation",
            })
        return decisions

    for critical_state in critical_states:
        entry = _entry_from_source(critical_state["source"], state)
        if entry is None:
            decisions.append({
                "state_id": critical_state["id"],
                "method": "ABSTAIN",
                "reason": "critical_state_source_unresolvable",
                "evidence_reliable": False,
                "machine_resolved": False,
                "user_authoritative": False,
            })
            continue

        key = entry["key"]
        memory_id = entry["id"]
        environment = case.get("environment", {})
        rel = reliability.score(
            entry,
            state,
            current_scope=environment.get("scope"),
            as_of=environment.get("as_of"),
        )
        base = {
            "state_id": critical_state["id"],
            "key": key,
            "memory_id": memory_id,
            "reliability": rel["reliability"],
            "reliability_signals": rel.get("signals", {}),
        }


        if rel["reliability"] >= RELIABILITY_THRESHOLD:
            decisions.append({
                **base,
                "method": "CONTINUE",
                "reason": "existing_evidence_reliable",
                "evidence_reliable": True,
            })
            continue


        verify_result = tools.try_verify(
            key,
            state,
            memory_id=memory_id,
            context=verification_context,
        )
        verification_status = verify_result.get("status", "INSUFFICIENT")
        if verification_status in RESOLVED_VERIFICATION_STATUSES:
            decisions.append({
                **base,
                "method": "VERIFY_STATE",
                "reason": "machine_verification_conclusive",
                "evidence_reliable": False,
                "machine_resolved": True,
                "verified_value": verify_result["value"],
                "tool": verify_result["tool"],
                "evidence": verify_result.get("evidence"),
                "verification_status": verification_status,
            })
            continue


        user_authoritative = key in human_authoritative_keys
        if user_authoritative:
            decisions.append({
                **base,
                "method": "ASK_STATE",
                "reason": "machine_cannot_resolve_user_is_authoritative",
                "evidence_reliable": False,
                "machine_resolved": False,
                "verification_status": verification_status,
                "user_authoritative": True,
            })
            continue


        decisions.append({
            **base,
            "method": "ABSTAIN",
            "reason": "unreliable_state_has_no_authoritative_resolution_source",
            "evidence_reliable": False,
            "machine_resolved": False,
            "verification_status": verification_status,
            "user_authoritative": False,
        })
    return decisions


def _entry_from_source(source, state):
    if not source.startswith("memory:"):
        return None
    mem_id = source.split(":", 1)[1]
    entry = state.get(mem_id)
    return entry
