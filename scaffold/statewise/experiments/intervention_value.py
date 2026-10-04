LAMBDA_FUTURE = 0.5
MU_RESOLVE_COST = 1.0
NU_UPDATE_RISK = 1.0


_RESOLVE_COST_BY_METHOD = {
    "VERIFY_STATE": 0.1,
    "ASK_STATE": 1.0,
    "ASK_PERMISSION": 0.8,
}


def future_benefit(critical_state, case):

    future_tasks = case.get("future_related_tasks", [])
    return float(len(future_tasks))


def resolution_cost(method):
    return _RESOLVE_COST_BY_METHOD.get(method, 1.0)


def update_risk(reliability_of_answer):

    return 1.0 - reliability_of_answer


def score(current_reliability, current_benefit, method, answer_reliability=0.9, case=None, critical_state=None):

    b_future = future_benefit(critical_state or {}, case or {})
    c_resolve = resolution_cost(method)
    r_update = update_risk(answer_reliability)

    siv = (1 - current_reliability) * (current_benefit + LAMBDA_FUTURE * b_future)
    siv -= MU_RESOLVE_COST * c_resolve
    siv -= NU_UPDATE_RISK * r_update

    return {
        "siv": siv,
        "b_current": current_benefit,
        "b_future": b_future,
        "c_resolve": c_resolve,
        "r_update": r_update,
        "worth_intervening": siv > 0,
    }
