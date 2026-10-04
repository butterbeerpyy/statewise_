from scaffold.statewise.agents import planner
from scaffold.statewise.core import main_loop, residual_risk
from scaffold.statewise.memory import memory_store


def gate_initial_action(case, condition="corrupted", proposed=None):

    case_id = case["case_id"]
    if proposed is None:
        state = memory_store.load()
        state = main_loop.apply_condition(state, case, condition)
        stage_suffix = "propose_action_initial_correct" if condition == "correct" else "propose_action_initial"
        proposed = planner.propose_action(
            case["task"],
            state,
            case_id=case_id,
            stage_suffix=stage_suffix,
            scope=case.get("environment", {}).get("scope"),
        )

    gate = residual_risk.gate(proposed["action"], rationale=proposed.get("rationale", ""))
    return {
        "proposed_action": proposed["action"],
        "gate_decision": gate["decision"],
        "impact": gate.get("impact"),
    }
