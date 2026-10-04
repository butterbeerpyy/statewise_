from scaffold.statewise.core import interceptor


def gate(final_action, rationale=""):

    impact = interceptor.classify(final_action)

    if impact["violates_hard_policy"]:
        return {"decision": "REFUSE", "impact": impact, "reason": "hard_policy_violation"}

    if impact["impact_score"] >= 2:
        return {"decision": "ASK_PERMISSION", "impact": impact, "reason": "intrinsic_action_risk"}

    return {"decision": "EXECUTE", "impact": impact}
