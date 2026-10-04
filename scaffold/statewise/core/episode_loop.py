from __future__ import annotations


COMPLETE = "COMPLETE"
SAFE_ABORT = "SAFE_ABORT"
REFUSED = "REFUSED"
TASK_FAILURE = "TASK_FAILURE"
SAFETY_FAILURE = "SAFETY_FAILURE"
STEP_LIMIT = "STEP_LIMIT"


def _step_type(step):
    if not isinstance(step, dict):
        raise TypeError("agent.step must return an object")
    explicit = step.get("type")
    if explicit:
        return str(explicit).upper()

    if "tool" in step and "operation" in step:
        return "ACTION"
    if isinstance(step.get("action"), dict):
        return "ACTION"
    raise ValueError("agent step has neither type nor structured action")


def run(
    agent,
    runtime,
    evaluator,
    user_simulator=None,
    permission_simulator=None,
    state_verifier=None,
    max_steps=8,
    initial_observation=None,
):

    observation = initial_observation
    trajectory = []

    for index in range(max_steps):
        step = agent.step(observation, tuple(trajectory))
        kind = _step_type(step)
        event = {"step": index, "type": kind, "agent_step": step}

        if kind == "DONE":
            trajectory.append(event)
            return {"status": COMPLETE, "steps": index + 1, "trajectory": trajectory}

        if kind == "ABSTAIN":
            trajectory.append(event)
            return {
                "status": SAFE_ABORT,
                "steps": index + 1,
                "trajectory": trajectory,
                "reason": step.get("reason", "agent_abstained"),
            }

        if kind == "REFUSE":
            trajectory.append(event)
            return {
                "status": REFUSED,
                "steps": index + 1,
                "trajectory": trajectory,
                "reason": step.get("reason", "policy_refusal"),
            }

        if kind == "TASK_FAILURE":
            trajectory.append(event)
            return {
                "status": TASK_FAILURE,
                "steps": index + 1,
                "trajectory": trajectory,
                "reason": step.get("reason", "agent_task_failure"),
            }

        if kind == "VERIFY_STATE":
            if state_verifier is None:
                event["error"] = "no_state_verifier"
                trajectory.append(event)
                return {
                    "status": SAFE_ABORT,
                    "steps": index + 1,
                    "trajectory": trajectory,
                    "reason": "verify_state_channel_unavailable",
                }
            observation = state_verifier.verify(step)
            event["result"] = observation
            trajectory.append(event)
            continue

        if kind == "ASK_STATE":
            if user_simulator is None:
                event["error"] = "no_user_simulator"
                trajectory.append(event)
                return {
                    "status": SAFE_ABORT,
                    "steps": index + 1,
                    "trajectory": trajectory,
                    "reason": "ask_state_channel_unavailable",
                }
            observation = user_simulator.answer(step)
            event["result"] = observation
            trajectory.append(event)
            continue

        if kind == "ASK_PERMISSION":
            if permission_simulator is None:
                event["error"] = "no_permission_simulator"
                trajectory.append(event)
                return {
                    "status": SAFE_ABORT,
                    "steps": index + 1,
                    "trajectory": trajectory,
                    "reason": "permission_channel_unavailable",
                }
            observation = permission_simulator.answer(step)
            event["result"] = observation
            trajectory.append(event)
            continue

        if kind != "ACTION":
            event["error"] = f"unsupported_control_step:{kind}"
            trajectory.append(event)
            return {
                "status": SAFE_ABORT,
                "steps": index + 1,
                "trajectory": trajectory,
                "reason": "unsupported_control_step",
            }

        action = step.get("action", step)
        event["action"] = action
        try:
            observation = runtime.execute(action)
        except Exception as exc:


            runtime_error = {
                "type": type(exc).__name__,
                "message": str(exc)[:500],
            }
            event["runtime_error"] = runtime_error
            observation = {"ok": False, "runtime_error": runtime_error}
            event["result"] = observation
            trajectory.append(event)
            continue

        event["result"] = observation
        trajectory.append(event)
        evaluator.observe(action, observation, tuple(trajectory))
        if evaluator.has_catastrophic_violation():
            return {
                "status": SAFETY_FAILURE,
                "steps": index + 1,
                "trajectory": trajectory,
                "reason": "catastrophic_oracle_violation",
            }


        oracle = observation.get("oracle", {}) if isinstance(observation, dict) else {}
        if index == max_steps - 1 and (
            oracle.get("task_completed") or oracle.get("acceptable_terminal")
        ):
            return {
                "status": COMPLETE,
                "steps": index + 1,
                "trajectory": trajectory,
                "reason": "terminal_oracle_at_step_boundary",
            }

    return {"status": STEP_LIMIT, "steps": max_steps, "trajectory": trajectory}
