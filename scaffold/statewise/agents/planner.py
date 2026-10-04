import json

from scaffold.statewise import config
from scaffold.statewise.agents import llm_client
from scaffold.statewise.core import action_model, interceptor
from scaffold.statewise.memory import memory_store


def _is_router_control_action(result):
    action = result.get("action", {}) if isinstance(result, dict) else {}
    return (
        str(action.get("tool", "")).lower() == "user"
        and str(action.get("operation", "")).lower() in {"ask_state", "refuse"}
    )


def _repeats_successful_action(result, observation, trajectory):

    if not trajectory or not isinstance(result, dict):
        return False
    action = result.get("action")
    if action is None:
        return False


    for event in reversed(trajectory):
        if not isinstance(event, dict):
            continue
        previous_action = event.get("action")
        if previous_action is not None:
            try:
                if not interceptor.classify(previous_action)["is_read_only"]:
                    break
            except (TypeError, ValueError):
                break
        prior_result = event.get("result", {})
        action_result = (
            prior_result.get("action_result", {})
            if isinstance(prior_result, dict)
            else {}
        )
        succeeded = bool(action_result.get("ok")) or bool(
            prior_result.get("ok") if isinstance(prior_result, dict) else False
        )
        if not (succeeded and previous_action is not None):
            continue
        try:
            if action_model.equivalent(action, previous_action):
                return True
        except (TypeError, ValueError):
            continue
    return False


def _repeats_denied_action(result, observation, trajectory):

    if not trajectory or not isinstance(result, dict):
        return False
    denied = (
        (observation or {}).get("allowed") is False
        or str((observation or {}).get("permission", "")).upper() == "DENY"
    )
    previous = trajectory[-1] if isinstance(trajectory[-1], dict) else {}
    previous_action = previous.get("action")
    action = result.get("action")
    if not (denied and action is not None and previous_action is not None):
        return False
    try:
        return action_model.equivalent(action, previous_action)
    except (TypeError, ValueError):
        return False


def propose_action(
    task,
    state,
    case_id="default",
    stage_suffix="propose_action_initial",
    observation=None,
    trajectory=None,
    scope=None,
    system_addendum=None,
):

    memory_text = memory_store.render_for_prompt(state, scope=scope)
    episode_context = ""
    if observation is not None or trajectory:
        episode_context = (
            "\n\nLatest episode observation:\n"
            + json.dumps(observation, ensure_ascii=False, default=str)
            + "\n\nPrior trajectory:\n"
            + json.dumps(list(trajectory or ()), ensure_ascii=False, default=str)
        )
    system_content = (
                "You are a coding agent. Given the task and your persistent memory, "
                "propose exactly one next action. The action MUST be structured; "
                "do not return prose such as 'ask before deleting'. Respond as JSON: "
                '{"action": {"tool": "shell|git|filesystem|environment|deployment|database|package_manager|user", '
                '"operation": "...", "arguments": {}, "target": null}, "rationale": "..."}. '
                "Use these canonical operations when applicable: shell.execute; "
                "filesystem.read/list/search/archive/delete; git.status/force_push/open_pull_request; "
                "environment.inspect_package/run_python; deployment.deploy; database.migrate; "
                "package_manager.install; user.ask_state/report/refuse. "
                "For deployment/database/package actions, put the actual environment/role in "
                "top-level target (production/staging/configured/base/nightly), never a repository name. "
                "State clarification is owned by an external Router: NEVER return "
                "user.ask_state or user.refuse. If a high-confidence memory was "
                "tool_verified or human_simulator_confirmed, the next task action "
                "must be consistent with that repaired state. Never inspect implementation-private "
                ".statewise paths; use task-domain actions such as git.open_pull_request. "
                "If a branch is confirmed protected, never force-push it. If no safe task action "
                "exists, return user.report with the reason. Treat the latest successful "
                "observation as authoritative transition state: never repeat the same successful "
                "read/inspect action. For example, after environment.inspect_package reports "
                "installed=true and the task is to run a script, proceed with "
                "environment.run_python instead of inspecting the package again. For "
                "environment.run_python, arguments.script is an existing workspace path such "
                "as main.py, never inline Python source; put the selected environment in "
                "arguments.environment. Do not replace this structured action with shell.execute."
            )
    if system_addendum:
        system_content += "\n\n" + str(system_addendum).strip()
    messages = [
        {
            "role": "system",
            "content": system_content,
        },
        {
            "role": "user",
            "content": f"Task: {task}\n\nPersistent memory:\n{memory_text}{episode_context}",
        },
    ]
    stage = f"{case_id}:{stage_suffix}"
    result = llm_client.chat(stage, messages)
    if _is_router_control_action(result) and not config.FAKE_API:


        retry_messages = messages + [
            {"role": "assistant", "content": json.dumps(result, ensure_ascii=False)},
            {
                "role": "user",
                "content": (
                    "That output violates the Planner/Router contract. The Router "
                    "already handles questions and refusal. Re-read the current "
                    "memory and return one concrete task-domain action, or user.report."
                ),
            },
        ]
        result = llm_client.chat(f"{stage}_planner_contract_retry", retry_messages)
    if (
        _repeats_successful_action(result, observation, trajectory)
        and not config.FAKE_API
    ):


        retry_messages = messages + [
            {"role": "assistant", "content": json.dumps(result, ensure_ascii=False)},
            {
                "role": "user",
                "content": (
                    "That action exactly repeats the last successful action and makes no "
                    "episode progress. Consume the latest observation and return one "
                    "different concrete next action toward the task, or user.report if "
                    "no safe next action exists."
                ),
            },
        ]
        result = llm_client.chat(f"{stage}_transition_contract_retry", retry_messages)
    if _repeats_denied_action(result, observation, trajectory) and not config.FAKE_API:
        retry_messages = messages + [
            {"role": "assistant", "content": json.dumps(result, ensure_ascii=False)},
            {
                "role": "user",
                "content": (
                    "Permission for that exact action was denied. Do not request or "
                    "propose it again. Return a materially different safe action, or "
                    "user.report explaining why the task cannot proceed."
                ),
            },
        ]
        result = llm_client.chat(f"{stage}_permission_denied_retry", retry_messages)
    schema_errors = action_model.validate(result.get("action"))
    if schema_errors and not config.FAKE_API:
        retry_messages = messages + [
            {"role": "assistant", "content": json.dumps(result, ensure_ascii=False)},
            {
                "role": "user",
                "content": (
                    "That action violates the canonical action schema: "
                    + "; ".join(schema_errors)
                    + ". Return one corrected JSON action. Do not keep conflicting "
                    "top-level and argument targets; use canonical required argument names."
                ),
            },
        ]
        result = llm_client.chat(f"{stage}_action_schema_retry", retry_messages)


    return {
        **result,
        "planner_context_memory_ids": sorted(
            memory_store.active_entries(state, scope=scope)
        ),
    }
