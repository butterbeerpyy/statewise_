from __future__ import annotations

import json
from typing import Any, Mapping

from scaffold.statewise import config
from scaffold.statewise.agents import llm_client
from scaffold.statewise.core import interceptor


REFERENCE = (
    "Ask or Assume? Uncertainty-Aware Clarification-Seeking in Coding Agents "
    "(arXiv:2603.26233)"
)
IMPLEMENTATION_FIDELITY = "clean_room_task_uncertainty_router_no_paper_checkpoint"


def fidelity_manifest() -> dict[str, Any]:
    return {
        "reference": REFERENCE,
        "implementation_fidelity": IMPLEMENTATION_FIDELITY,
        "decision_unit": "task_and_proposal_underspecification",
        "persistent_state_provenance": False,
        "memory_repair": False,
        "decision_critical_state_detection": False,
        "question_budget": 2,
    }


def decide(
    case: Mapping[str, Any],
    proposal: Mapping[str, Any],
    *,
    question_count: int,
    observation: Mapping[str, Any] | None = None,
    trajectory: Any = None,
) -> dict[str, Any]:

    action = proposal.get("action") or {}
    impact = interceptor.classify(action)
    if impact.get("violates_hard_policy"):
        return {"decision": "REFUSE", "question": None, "reason": "hard_policy_violation"}
    if impact.get("is_read_only") or config.FAKE_API:
        return {"decision": "EXECUTE", "question": None, "reason": "task_is_sufficiently_specified"}

    payload = {
        "task": case.get("task"),
        "proposed_action": action,
        "agent_rationale": proposal.get("rationale", ""),
        "question_count": question_count,
        "latest_observation": observation,
        "recent_trajectory": list(trajectory or ())[-8:],
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You are an uncertainty-aware clarification policy for a coding agent. "
                "Decide only whether the user task and proposed action are sufficiently "
                "specified to proceed. Do not inspect or reason about hidden benchmark "
                "fields, persistent-memory provenance, reliability, or decision-critical "
                "state. Ask one concise free-form question only when missing task/context "
                "information could materially change the action. Otherwise execute. Refuse "
                "only a hard policy violation. Return exactly "
                "{\"decision\":\"EXECUTE|ASK|REFUSE\",\"question\":null|\"...\","
                "\"reason\":\"...\"}."
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
    ]
    result = llm_client.chat(
        f"{case.get('case_id', 'default')}:ask_or_assume_{question_count}", messages
    )
    decision = str(result.get("decision", "REFUSE")).upper()
    if decision not in {"EXECUTE", "ASK", "REFUSE"}:
        decision = "REFUSE"
    question = str(result.get("question") or "").strip() or None
    if decision == "ASK" and question is None:
        decision = "REFUSE"
    return {
        "decision": decision,
        "question": question,
        "reason": str(result.get("reason", "unspecified"))[:500],
        "implementation_fidelity": IMPLEMENTATION_FIDELITY,
    }
