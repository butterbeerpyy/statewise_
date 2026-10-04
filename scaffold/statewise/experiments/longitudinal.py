from __future__ import annotations

from scaffold.statewise.agents import planner
from scaffold.statewise.core import main_loop, residual_risk
from scaffold.statewise.memory import memory_store


def run_episode(case_path, memory_path, condition="corrupted"):
    case = main_loop.load_case(case_path)
    initial = main_loop.run_case(
        case_path,
        condition=condition,
        support_track="automatic",
        persist=True,
        memory_path=memory_path,
    )

    followups = []
    for index, task in enumerate(case.get("future_related_tasks", []), start=1):
        state = memory_store.load(memory_path)
        proposal = planner.propose_action(
            task,
            state,
            case_id=case["case_id"],
            stage_suffix=f"followup_{index}",
            scope=case.get("environment", {}).get("scope"),
        )
        gate = residual_risk.gate(proposal["action"], proposal.get("rationale", ""))
        followups.append({
            "task": task,
            "action": proposal["action"],
            "gate": gate,
            "active_memory_ids": sorted(
                memory_store.active_entries(
                    state, scope=case.get("environment", {}).get("scope")
                )
            ),
        })
    return {"initial": initial, "followups": followups, "memory_path": str(memory_path)}
