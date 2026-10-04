import copy

from scaffold.statewise.agents import llm_client, planner
from scaffold.statewise.core import action_model, attribution


def _generate_alt_values(state_claim, current_value, stage):
    messages = [
        {
            "role": "system",
            "content": (
                "A persistent-memory claim may be stale or wrong. Without access to any "
                "benchmark answer, propose 2-3 plausible alternative values covering "
                "materially different practical implications. Do not return near-synonyms "
                "or claim that one value is the truth. Respond as JSON: "
                "{\"alt_values\": [\"...\", \"...\"]}"
            ),
        },
        {
            "role": "user",
            "content": f"Claim: {state_claim}\nCurrent value: {current_value}",
        },
    ]
    result = llm_client.chat(stage, messages)


    values = result.get("alt_values")
    if not isinstance(values, list):
        values = [result["alt_value"]]
    unique = []
    for value in values:
        if value == current_value or value in unique:
            continue
        unique.append(value)
    return unique


def _automatic_interventions(state_claim, current_value, stage):
    interventions = [
        {"kind": "remove", "value": None},
        {"kind": "mark_uncertain", "value": current_value},
    ]
    interventions.extend(
        {"kind": "replace", "value": value}
        for value in _generate_alt_values(state_claim, current_value, stage)
    )
    return interventions


def _apply_intervention(state, mem_id, intervention):
    alt_state = copy.deepcopy(state)
    kind = intervention["kind"]
    if kind == "remove":
        alt_state.pop(mem_id, None)
    elif kind == "mark_uncertain":
        alt_state[mem_id]["confidence"] = "low"
        alt_state[mem_id]["text"] = (
            f"{alt_state[mem_id].get('key')} is uncertain; do not assume its current value"
        )
    else:
        value = intervention["value"]
        alt_state[mem_id]["value"] = value
        alt_state[mem_id]["text"] = f"{alt_state[mem_id].get('key')} = {value}"
    return alt_state


def detect(
    task,
    state,
    original_action,
    support_states,
    case_id="default",
    stage_suffix="",
    interventions=None,
    precomputed_alt_actions=None,
    original_rationale="",
    scope=None,
):

    annotated = []
    interventions = interventions or {}
    precomputed_alt_actions = precomputed_alt_actions or {}
    for s in support_states:
        if not s["source"].startswith("memory:"):
            annotated.append({**s, "critical": False, "alt_action": None})
            continue

        mem_id = s["source"].split(":", 1)[1]
        entry = state.get(mem_id)
        if entry is None:
            annotated.append({**s, "critical": False, "alt_action": None})
            continue

        if mem_id in interventions:


            probes = [{"kind": "oracle_replace", "value": interventions[mem_id]}]
        else:
            alt_value_stage = f"{case_id}:alt_value_{s['id']}{stage_suffix}"
            probes = _automatic_interventions(s["claim"], entry["value"], alt_value_stage)

        probe_results = []
        for probe_index, probe in enumerate(probes):
            alt_state = _apply_intervention(state, mem_id, {
                "kind": "replace" if probe["kind"] == "oracle_replace" else probe["kind"],
                "value": probe["value"],
            })
            if mem_id in precomputed_alt_actions and probe_index == 0:
                alt_plan = {"action": precomputed_alt_actions[mem_id], "rationale": ""}
            else:
                counterfactual_stage = f"counterfactual_{s['id']}{stage_suffix}"
                alt_plan = planner.propose_action(
                    task,
                    alt_state,
                    case_id=case_id,
                    stage_suffix=counterfactual_stage,
                    scope=scope,
                )
            alt_plan = {
                **alt_plan,
                "action": action_model.contextualize(alt_plan["action"], alt_state),
            }
            changed = not action_model.equivalent(alt_plan["action"], original_action)
            delta, signals = attribution.counterfactual_delta(
                original_action,
                alt_plan["action"],
                original_rationale=original_rationale,
                alternative_rationale=alt_plan.get("rationale", ""),
            )
            probe_results.append({
                "kind": probe["kind"],
                "value": probe["value"],
                "action": alt_plan["action"],
                "rationale": alt_plan.get("rationale", ""),
                "action_changed": changed,
                "delta": delta,
                "change_signals": signals,
            })

        best = max(probe_results, key=lambda item: (item["delta"], item["action_changed"]))
        changed_count = sum(item["action_changed"] for item in probe_results)
        stability = changed_count / len(probe_results)
        action_changed = changed_count > 0


        delta_cf = sum(item["delta"] for item in probe_results) / len(probe_results)
        delta_cf = round(delta_cf, 4)

        annotated.append(
            {
                **s,


                "action_changed": action_changed,
                "delta_cf": delta_cf,
                "counterfactual_change_signals": best["change_signals"],
                "counterfactual_interventions_tested": len(probe_results),
                "counterfactual_stability": stability,
                "counterfactual_probes": probe_results,
                "alt_value": best["value"] if action_changed else None,
                "alt_action": best["action"] if action_changed else None,
                "alt_rationale": best["rationale"] if action_changed else None,
            }
        )
    return annotated


def filter_critical(annotated_states):
    return [s for s in annotated_states if s["critical"]]
