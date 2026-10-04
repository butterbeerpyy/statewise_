import copy
import json

from scaffold.statewise.agents import human_simulator, planner
from scaffold.statewise.core import (
    action_model,
    attribution,
    critical_detect,
    extract_states,
    interceptor,
    question_gen,
    residual_risk,
    route,
    state_action_gate,
)
from scaffold.statewise.evaluation import measurement
from scaffold.statewise.evaluation import case_schema, safety_eval
from scaffold.statewise.memory import memory_repair, memory_store
from scaffold.statewise import config


def load_case(case_path):
    with open(case_path, "r", encoding="utf-8") as f:
        return json.load(f)


def apply_condition(state, case, condition):

    if condition is None or "memory_id" not in case:
        return state
    mem_id = case["memory_id"]
    key = case["memory_key"]
    if condition == "no_memory":


        state.clear()
        return state
    if condition not in {"corrupted", "correct"}:
        raise ValueError(f"unknown paired condition: {condition}")
    condition_state = case[f"{condition}_state"]


    for record in case.get("context_memories", []):
        context_entry = dict(record)
        context_entry.setdefault("scope", dict(memory_store.DEFAULT_SCOPE))
        context_entry.setdefault("status", "active")
        context_entry.setdefault("supersedes", [])
        context_entry.setdefault("ttl_days", None)
        context_entry.setdefault("evidence", None)
        context_entry.setdefault("updated_at", "session-1")
        state[context_entry["id"]] = context_entry

    merged = dict(state.get(mem_id, {}))


    merged.update(case.get("state_metadata", {}))
    merged.update(condition_state)
    merged["id"] = mem_id
    merged["key"] = key
    merged.setdefault("scope", dict(memory_store.DEFAULT_SCOPE))
    merged.setdefault("status", "active")
    merged.setdefault("supersedes", [])
    merged.setdefault("ttl_days", None)
    merged.setdefault("evidence", None)
    merged.setdefault("updated_at", "session-1")
    state[mem_id] = merged
    return state


MAX_REPLAN_CYCLES = 3


def _inspect_proposal(
    proposal,
    task,
    state,
    case,
    condition,
    support_track,
    counterfactual_track,
    cycle,
    human_authoritative_keys,
    counterfactual_actions=None,
    verification_context=None,
):

    case_id = case["case_id"]
    case_scope = case.get("environment", {}).get("scope")
    context_ids = proposal.get(
        "planner_context_memory_ids",
        sorted(memory_store.active_entries(state, scope=case_scope)),
    )
    proposal = {
        **proposal,
        "action": action_model.contextualize(proposal["action"], state),
    }
    impact = interceptor.classify(proposal["action"])
    inspected = {
        "cycle": cycle,
        "attribution_policy": attribution.current_policy(),
        "action": proposal["action"],
        "rationale": proposal.get("rationale", ""),
        "planner_context_memory_ids": context_ids,
        "action_schema_errors": action_model.validate(proposal.get("action")),
        "impact": impact,
        "support_states": [],
        "annotated_states": [],
        "attribution_metrics": {},
        "critical_states": [],
        "routing_decisions": [],
    }
    if impact["is_read_only"]:
        return proposal, inspected


    effective_condition = condition if cycle == 0 else "correct"
    extract_suffix = (
        "extract_states_correct" if effective_condition == "correct" else "extract_states"
    )
    if support_track == "oracle":
        support_states = extract_states.from_oracle(case, state)
    elif support_track == "automatic":
        support_states = extract_states.extract(
            proposal["action"],
            state,
            case_id=case_id,
            stage_suffix=extract_suffix,
            scope=case_scope,
        )
    else:
        raise ValueError(f"unknown support track: {support_track}")
    scored = attribution.score_candidates(
        support_states,
        state,
        proposal["action"],
        proposal.get("rationale", ""),
        context_ids,
        impact,
        oracle=support_track == "oracle",
    )

    interventions = {}
    if (
        counterfactual_track == "oracle"
        and "memory_id" in case
        and effective_condition in {"corrupted", "correct"}
    ):
        opposite = "correct_state" if effective_condition == "corrupted" else "corrupted_state"
        active_entry = memory_store.find_by_key(
            state, case.get("memory_key"), scope=case_scope
        )
        if active_entry is not None:
            interventions[active_entry["id"]] = case[opposite]["value"]
    detect_suffix = "_correct" if effective_condition == "correct" else ""
    detected = critical_detect.detect(
        task,
        state,
        proposal["action"],
        attribution.selected_for_counterfactual(scored),
        case_id=case_id,
        stage_suffix=detect_suffix,
        interventions=interventions,
        precomputed_alt_actions=counterfactual_actions if cycle == 0 else None,
        original_rationale=proposal.get("rationale", ""),
        scope=case_scope,
    )
    annotated = attribution.finalize(scored, detected)
    critical_states = critical_detect.filter_critical(annotated)
    decisions = route.route(
        critical_states,
        state,
        impact,
        case=case,
        human_authoritative_keys=human_authoritative_keys,
        verification_context=verification_context,
    )
    inspected.update({
        "support_states": scored,
        "annotated_states": annotated,
        "attribution_metrics": attribution.stage_metrics(
            annotated, case.get("oracle_support_states", [])
        ),
        "critical_states": [item["id"] for item in critical_states],
        "routing_decisions": decisions,
    })
    return proposal, inspected


def run_case(
    case_path,
    condition="corrupted",
    support_track="automatic",
    counterfactual_track="automatic",
    persist=False,
    memory_path=None,
    initial_proposal=None,
    counterfactual_actions=None,
    max_replan_cycles=MAX_REPLAN_CYCLES,
    verification_context=None,
    initial_state=None,
    initial_observation=None,
    trajectory=None,
    initial_stage_suffix=None,
):

    case = load_case(case_path)
    case_schema.assert_valid(case)
    if counterfactual_track not in {"automatic", "oracle"}:
        raise ValueError(f"unknown counterfactual track: {counterfactual_track}")

    case_id = case["case_id"]
    task = case["task"]
    state = (
        copy.deepcopy(initial_state)
        if initial_state is not None
        else apply_condition(memory_store.load(memory_path), case, condition)
    )


    human_authoritative_keys = human_simulator.authoritative_keys(case)

    initial_suffix = initial_stage_suffix or {
        "correct": "propose_action_initial_correct",
        "no_memory": "propose_action_initial_no_memory",
    }.get(condition, "propose_action_initial")
    proposal = initial_proposal or planner.propose_action(
        task,
        state,
        case_id=case_id,
        stage_suffix=initial_suffix,
        observation=initial_observation,
        trajectory=trajectory,
        scope=case.get("environment", {}).get("scope"),
    )
    log = {
        "task": task,
        "case_id": case_id,
        "condition": condition,
        "support_track": support_track,
        "counterfactual_track": counterfactual_track,
        "attribution_policy": attribution.current_policy(),
        "inspection_rounds": [],
    }
    all_decisions = []
    questions = []
    human_interactions = []
    terminal_action = None
    gate_result = None

    for cycle in range(max_replan_cycles + 1):
        proposal, inspected = _inspect_proposal(
            proposal,
            task,
            state,
            case,
            condition,
            support_track,
            counterfactual_track,
            cycle,
            human_authoritative_keys,
            counterfactual_actions=counterfactual_actions,
            verification_context=verification_context,
        )
        log["inspection_rounds"].append(inspected)
        all_decisions.extend(inspected["routing_decisions"])

        if cycle == 0:
            log.update({
                "action_schema_errors": inspected["action_schema_errors"],
                "initial_action": inspected["action"],
                "initial_rationale": inspected["rationale"],
                "planner_context_memory_ids": inspected["planner_context_memory_ids"],
                "initial_impact": inspected["impact"],
                "support_states": inspected["support_states"],
                "annotated_states": inspected["annotated_states"],
                "attribution_metrics": inspected["attribution_metrics"],
                "critical_states": inspected["critical_states"],
            })

        if inspected["action_schema_errors"]:
            terminal_action = proposal.get("action")
            gate_result = {
                "decision": "REFUSE",
                "reason": "invalid_action_schema",
                "schema_errors": inspected["action_schema_errors"],
            }
            break
        if inspected["impact"]["is_read_only"]:
            terminal_action = proposal["action"]
            gate_result = {"decision": "EXECUTE", "impact": inspected["impact"]}
            break
        if any(item["method"] == "REFUSE" for item in inspected["routing_decisions"]):
            gate_result = {"decision": "REFUSE", "reason": "hard_policy_violation"}
            break

        repaired = False
        for decision in inspected["routing_decisions"]:
            if decision["method"] == "VERIFY_STATE":
                memory_repair.repair(
                    state,
                    key=decision["key"],
                    value=decision["verified_value"],
                    source=f"tool_verified:{decision['tool']}",
                    confidence="high",
                    evidence={"tool": decision["tool"], "detail": decision.get("evidence")},
                    scope=case.get("environment", {}).get("scope"),
                    supersede_id=decision.get("memory_id"),
                )
                repaired = True
            elif decision["method"] == "ASK_STATE":
                question = question_gen.ask_state_question(decision, state, case=case)
                questions.append(question)
                try:
                    response = human_simulator.answer(question, case)
                except Exception as exc:


                    response = {
                        "known": False,
                        "answer_text": "",
                        "value": None,
                        "confidence": "low",
                        "api_role": "human_simulator",
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:300],
                    }
                interaction = {
                    "cycle": cycle,
                    "state_key": decision["key"],
                    "question": question,
                    "answer": response,
                }
                human_interactions.append(interaction)
                if response.get("known") and "value" in response:
                    new_memory_id = memory_repair.repair(
                        state,
                        key=decision["key"],
                        value=response["value"],
                        source="human_simulator_confirmed",
                        confidence=response.get("confidence", "medium"),
                        evidence={
                            "question": question["question"],
                            "answer": response.get("answer_text", ""),
                            "api_role": response.get("api_role"),
                        },
                        scope=question.get("scope") or case.get("environment", {}).get("scope"),
                        supersede_id=decision.get("memory_id"),
                    )
                    interaction["memory_update"] = {
                        "memory_id": new_memory_id,
                        "value": response["value"],
                    }
                    repaired = True
                else:
                    interaction["memory_update"] = None

        if repaired:
            if persist:
                memory_store.save(state, memory_path)
            if cycle >= max_replan_cycles:
                gate_result = {"decision": "REFUSE", "reason": "max_replan_cycles_exceeded"}
                break
            replan_suffix = (
                "replan_final_correct"
                if condition == "correct" or cycle > 0
                else "replan_final"
            )
            proposal = planner.propose_action(
                task,
                state,
                case_id=case_id,
                stage_suffix=replan_suffix,
                observation=initial_observation,
                trajectory=trajectory,
                scope=case.get("environment", {}).get("scope"),
            )
            continue

        terminal_action = proposal["action"]
        if any(item["method"] == "ABSTAIN" for item in inspected["routing_decisions"]):
            gate_result = {
                "decision": "REFUSE",
                "impact": inspected["impact"],
                "reason": "unresolved_action_critical_state",
                "safe_fallback": "ABSTAIN",
            }
        elif any(
            item["method"] == "ASK_STATE" for item in inspected["routing_decisions"]
        ):
            gate_result = {
                "decision": "REFUSE",
                "impact": inspected["impact"],
                "reason": "human_state_answer_unresolved",
                "safe_fallback": "ABSTAIN",
            }
        else:


            state_gate = state_action_gate.gate(
                terminal_action,
                state,
                case.get("safety", {}),
                scope=case.get("environment", {}).get("scope"),
            )
            if state_gate["decision"] == "REWRITE":
                terminal_action = state_gate["rewrite_action"]
                gate_result = residual_risk.gate(
                    terminal_action,
                    rationale=f"state_action_rewrite:{state_gate.get('reason')}",
                )
                gate_result["state_action_rewrite"] = state_gate
            elif state_gate["decision"] != "CONTINUE":
                gate_result = state_gate
            else:
                gate_result = residual_risk.gate(
                    terminal_action, rationale=proposal.get("rationale", "")
                )
        break

    log["routing_decisions"] = all_decisions
    log["questions_asked"] = questions
    log["human_interactions"] = human_interactions
    log["replan_count"] = max(0, len(log["inspection_rounds"]) - 1)
    log["episode_attribution_metrics"] = measurement.aggregate_episode_attribution(
        case, log["inspection_rounds"]
    )
    log["final_action"] = terminal_action
    log["final_memory"] = state
    log["residual_gate"] = gate_result or {
        "decision": "REFUSE", "reason": "loop_terminated_without_decision"
    }
    log["safety_evaluation"] = safety_eval.evaluate(
        terminal_action, log["residual_gate"]["decision"], case.get("safety", {})
    )
    return log


if __name__ == "__main__":
    import os
    import sys

    case_file = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        config.SCAFFOLD_ROOT, "cases", "case_env_nightly.json"
    )
    result = run_case(case_file)
    print(json.dumps(result, indent=2, ensure_ascii=False))
