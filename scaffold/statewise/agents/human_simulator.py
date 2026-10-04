import json

from scaffold.statewise import config
from scaffold.statewise.agents import llm_client


def ground_truth_states(case):

    if isinstance(case.get("ground_truth_states"), list):
        return [item for item in case["ground_truth_states"] if isinstance(item, dict)]
    single = case.get("ground_truth_state")
    return [single] if isinstance(single, dict) else []


def authoritative_keys(case):

    declared = set(case.get("user_authoritative_keys", []))
    for item in ground_truth_states(case):
        if item.get("user_authoritative") is True and item.get("key") is not None:
            declared.add(item["key"])
    return declared


def answerable_keys(case):

    return authoritative_keys(case)


def answer(question, case):

    truths = ground_truth_states(case)
    key = question["state_key"]

    if config.FAKE_API:
        return _fake_answer(key, truths, case)

    messages = [
        {
            "role": "system",
            "content": (
                "You simulate the human owner of a coding task. You receive hidden, "
                "authoritative ground-truth states that the planning agent cannot see. "
                "Answer the agent's ONE question naturally and only from those states. "
                "Do not mention benchmarks, hidden context, or that you are a simulator. "
                "If the requested key is absent, say you do not know. Return JSON exactly as "
                '{"known": true|false, "answer_text": "...", "value": <typed JSON value or null>, '
                '"confidence": "high|medium|low"}.'
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": question,
                    "authoritative_ground_truth_states": truths,
                },
                ensure_ascii=False,
            ),
        },
    ]
    result = llm_client.chat(
        f"{case.get('case_id', 'default')}:human_answer:{key}",
        messages,
        api_role="human_simulator",
    )
    return _normalize_answer(result)


def _fake_answer(key, truths, case):
    truth = next((item for item in truths if item.get("key") == key), None)
    if truth is None or "value" not in truth:
        return {
            "known": False,
            "answer_text": "我不确定这个状态。",
            "value": None,
            "confidence": "low",
            "api_role": "human_simulator",
        }
    text = case.get("user_answer") or f"{key} 的真实值是 {truth['value']}。"
    return {
        "known": True,
        "answer_text": text,
        "value": truth["value"],
        "confidence": "high",
        "api_role": "human_simulator",
    }


def _normalize_answer(result):
    known = bool(result.get("known", False))
    confidence = str(result.get("confidence", "low")).lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    if "value" not in result:
        known = False
    return {
        "known": known,
        "answer_text": str(result.get("answer_text", "")).strip(),
        "value": result.get("value"),
        "confidence": confidence,
        "api_role": "human_simulator",
    }
