from __future__ import annotations

from scaffold.statewise.evaluation import safety_eval


class CasePermissionSimulator:
    def __init__(self, case):
        self.case = case

    def answer(self, request):
        action = request.get("action")
        policy = self.case.get("permission_policy", {})
        for rule in policy.get("rules", []):
            if safety_eval.action_matches(action, rule.get("action", {})):
                decision = str(rule.get("decision", "DENY")).upper()
                return {
                    "permission": decision,
                    "allowed": decision == "ALLOW",
                    "reason": rule.get("reason", "case_permission_rule"),
                    "source": "deterministic_case_policy",
                }
        decision = str(policy.get("default", "DENY")).upper()
        return {
            "permission": decision,
            "allowed": decision == "ALLOW",
            "reason": "case_permission_default",
            "source": "deterministic_case_policy",
        }
