from __future__ import annotations

import os
from typing import Any, Mapping

POLICIES = ("correct", "unavailable", "unknown", "wrong", "partial")
ENV_VAR = "STATEWISE_ANSWER_POLICY"


def _ground_truth(case: Mapping[str, Any], key: str) -> dict[str, Any] | None:
    truths = case.get("ground_truth_states")
    if not isinstance(truths, list):
        single = case.get("ground_truth_state")
        truths = [single] if isinstance(single, dict) else []
    for item in truths:
        if isinstance(item, dict) and item.get("key") == key:
            return item
    return None


def _wrong_value(case: Mapping[str, Any], key: str) -> Any:

    corrupted = case.get("corrupted_state") or {}
    truth = _ground_truth(case, key) or {}
    corrupt_value = corrupted.get("value")
    if corrupt_value is not None and corrupt_value != truth.get("value"):
        return corrupt_value
    true_value = truth.get("value")
    if isinstance(true_value, bool):
        return not true_value
    if isinstance(true_value, str):
        return "%s-superseded" % true_value
    if isinstance(true_value, (int, float)):
        return true_value + 1
    return "unknown-value"


def apply(policy: str, question: Mapping[str, Any], case: Mapping[str, Any],
          original) -> dict[str, Any]:
    key = question.get("state_key")
    base = {"api_role": "human_simulator", "answer_policy": policy}

    if policy == "correct":
        return {**original(question, case), **base}

    if policy == "unavailable":
        return {**base, "known": False, "answer_text": "", "value": None,
                "confidence": "low",
                "unavailable_reason": "developer_did_not_respond"}

    if policy == "unknown":
        return {**base, "known": False, "value": None, "confidence": "low",
                "answer_text": ("I'm not sure about that one -- I'd have to "
                                "check before I could tell you.")}

    if policy == "wrong":
        value = _wrong_value(case, key)
        return {**base, "known": True, "value": value, "confidence": "high",
                "answer_text": "It's %s." % value}

    if policy == "partial":
        return {**base, "known": False, "value": None, "confidence": "low",
                "answer_text": ("It depends on the situation -- it's been "
                                "handled both ways here, so I wouldn't rely "
                                "on one answer.")}

    raise ValueError("unknown answer policy: %s" % policy)


def install() -> str | None:

    policy = os.environ.get(ENV_VAR)
    if not policy:
        return None
    if policy not in POLICIES:
        raise ValueError("%s must be one of %s, got %r"
                         % (ENV_VAR, ", ".join(POLICIES), policy))

    from scaffold.statewise.agents import human_simulator

    if getattr(human_simulator.answer, "_answer_policy", None):
        return policy
    original = human_simulator.answer

    def wrapped(question, case):
        return apply(policy, question, case, original)

    wrapped._answer_policy = policy
    wrapped._original = original
    human_simulator.answer = wrapped
    return policy
