from __future__ import annotations

import os

ENV_VAR = "STATEWISE_RESIDUAL_IMPACT_THRESHOLD"
DEFAULT_THRESHOLD = 2


def install() -> int | None:
    raw = os.environ.get(ENV_VAR)
    if raw is None or raw == "":
        return None
    try:
        threshold = int(raw)
    except ValueError:
        raise ValueError("%s must be an integer, got %r" % (ENV_VAR, raw))
    if not 0 <= threshold <= 4:
        raise ValueError("%s must be in [0, 4], got %d" % (ENV_VAR, threshold))

    from scaffold.statewise.core import residual_risk

    if getattr(residual_risk.gate, "_impact_threshold", None) is not None:
        return threshold
    original = residual_risk.gate

    def wrapped(final_action, rationale=""):
        result = original(final_action, rationale)


        if result.get("reason") == "hard_policy_violation":
            return result
        impact = result.get("impact") or {}
        score = int(impact.get("impact_score") or 0)
        if score >= threshold:
            return {"decision": "ASK_PERMISSION", "impact": impact,
                    "reason": "intrinsic_action_risk",
                    "impact_threshold": threshold}
        return {"decision": "EXECUTE", "impact": impact,
                "impact_threshold": threshold}

    wrapped._impact_threshold = threshold
    wrapped._original = original
    residual_risk.gate = wrapped
    return threshold
