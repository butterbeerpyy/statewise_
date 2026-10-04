from scaffold.statewise.core import action_model
from scaffold.statewise.memory import memory_store


def ask_state_question(decision, state, case=None):

    key = decision["key"]
    entry = state.get(decision.get("memory_id"))
    if entry is None or entry.get("status", "active") != "active":
        entry = memory_store.find_by_key(
            state,
            key,
            scope=(case or {}).get("environment", {}).get("scope"),
        )
    current_value = entry["value"] if entry else None

    evidence = [f"agent memory records {key} = {current_value!r} (confidence: {entry.get('confidence') if entry else 'unknown'})"]
    if case and case.get("conflicting_evidence"):
        evidence.append(case["conflicting_evidence"])

    return {
        "state_key": key,
        "question": f"当前记录的 {key} 是 {current_value!r}，但这与其他证据存在冲突。真实情况是什么？",
        "evidence": evidence,
        "options": ["保持当前记录", "提供正确值", "不确定 / Unknown"],
        "scope": entry.get("scope") if entry else memory_store.DEFAULT_SCOPE,
    }


def ask_permission_prompt(action, rationale, residual_risk):

    return {
        "action": action,
        "rationale": rationale,
        "residual_risk": residual_risk,
        "prompt": f"已确认相关状态。是否仍要执行：{action_model.display(action)}？（剩余风险：{residual_risk}）",
    }
