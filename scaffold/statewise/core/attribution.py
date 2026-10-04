from __future__ import annotations

from contextlib import contextmanager
import json
import re

from scaffold.statewise.core import action_model, interceptor


ATTR_WEIGHTS = {
    "provenance": 0.25,
    "grounding": 0.35,
    "counterfactual": 0.40,
}
CHEAP_FILTER_THRESHOLD = 0.30
FINAL_ATTR_THRESHOLD = 0.55
MAX_CF_CANDIDATES = 3
ATTRIBUTION_POLICIES = {"weighted", "staged"}
STAGED_COUNTERFACTUAL_DELTA = 0.50
STAGED_COUNTERFACTUAL_STABILITY = 0.50
_ACTIVE_POLICY = "weighted"


def current_policy():
    return _ACTIVE_POLICY


@contextmanager
def use_policy(policy):

    if policy not in ATTRIBUTION_POLICIES:
        raise ValueError(f"unknown attribution policy: {policy}")
    global _ACTIVE_POLICY
    previous = _ACTIVE_POLICY
    _ACTIVE_POLICY = policy
    try:
        yield
    finally:
        _ACTIVE_POLICY = previous


GROUNDING_BY_MUTATION = {
    "package_install": {
        "project_env": ("used_to_fill_argument", "target", 0.75),
        "dependency_install_allowed": ("action_necessity", None, 0.45),
    },
    "git_force_push": {
        "branch_is_protected": ("action_necessity", "force", 0.65),
        "current_branch": ("used_to_fill_argument", "branch", 0.75),
    },
    "git_push": {
        "branch_is_protected": ("action_necessity", "force", 0.60),
        "current_branch": ("used_to_fill_argument", "branch", 0.75),
    },
    "deploy": {"deploy_target": ("used_to_fill_argument", "target", 0.85)},
    "db_migrate": {"database_role": ("used_to_fill_argument", "target", 0.85)},
    "filesystem_delete": {
        "output_dir_status": ("action_necessity", "path", 0.65),
        "old_configs_usage_status": ("action_necessity", "path", 0.65),
    },
}


def _round(value):
    return round(max(0.0, min(1.0, float(value))), 4)


def _memory_id(candidate):
    source = candidate.get("source", "")
    return source.split(":", 1)[1] if source.startswith("memory:") else None


def _action_text(action):
    return json.dumps(action_model.normalize(action), ensure_ascii=False, sort_keys=True).lower()


def _meaningful_tokens(value):
    return {
        token for token in re.findall(r"[a-z0-9]+", str(value).lower().replace("_", " "))
        if len(token) >= 3 and token not in {"the", "this", "that", "true", "false", "none", "status"}
    }


def _token_trace(value, text, minimum_ratio):
    tokens = _meaningful_tokens(value)
    if len(tokens) < 2:
        return False
    text_tokens = _meaningful_tokens(text)
    return len(tokens & text_tokens) / len(tokens) >= minimum_ratio


def provenance_signal(candidate, entry, planner_context_memory_ids, action, rationale):

    mem_id = entry["id"]
    context_ids = set(planner_context_memory_ids or [])
    if mem_id not in context_ids:
        return 0.0, ["not_in_planner_context"]

    score = 0.40
    basis = ["entered_planner_context"]
    rationale_text = str(rationale or "").lower()
    key_text = str(entry.get("key", "")).lower()
    value_text = str(entry.get("value", "")).lower()
    if key_text and (
        key_text in rationale_text or _token_trace(key_text, rationale_text, 0.67)
    ):
        score += 0.30
        basis.append("key_in_rationale")
    elif len(value_text) >= 3 and value_text not in {"true", "false", "none"} and (
        value_text in rationale_text or _token_trace(value_text, rationale_text, 0.60)
    ):
        score += 0.30
        basis.append("value_in_rationale")

    action_text = _action_text(action)
    if len(value_text) >= 2 and value_text not in {"true", "false", "none"} and value_text in action_text:
        score += 0.30
        basis.append("value_flows_to_action")
    return _round(score), basis


def grounding_signal(candidate, entry, action, impact):

    normalized = action_model.normalize(action)
    value_text = str(entry.get("value", "")).lower()
    target_text = str(normalized.get("target") or "").lower()
    arguments_text = json.dumps(normalized.get("arguments", {}), ensure_ascii=False, sort_keys=True).lower()
    if value_text not in {"", "true", "false", "none"} and value_text == target_text:
        return 1.0, "used_to_fill_argument", "target", ["exact_target_match"]
    if len(value_text) >= 2 and value_text not in {"true", "false", "none"} and value_text in arguments_text:
        return 0.95, "used_to_fill_argument", "arguments", ["exact_argument_value_match"]

    best = (0.0, candidate.get("relation"), candidate.get("supported_argument"), [])
    key = entry.get("key")
    for mutation in impact.get("mutation_types", []):
        spec = GROUNDING_BY_MUTATION.get(mutation, {}).get(key)
        if spec and spec[2] > best[0]:
            best = (spec[2], spec[0], spec[1], [f"mutation_key_rule:{mutation}:{key}"])


    if candidate.get("grounder_declared"):
        declared_relation = candidate.get("relation")
        declared_score = 0.80 if declared_relation and candidate.get("supported_argument") else 0.55
        if declared_score > best[0]:
            best = (
                declared_score,
                declared_relation or "action_necessity",
                candidate.get("supported_argument"),
                ["batched_grounder_declaration"],
            )
        else:
            best[3].append("batched_grounder_declaration")
    return _round(best[0]), best[1], best[2], best[3]


def score_candidates(
    candidates,
    state,
    action,
    rationale,
    planner_context_memory_ids,
    impact,
    oracle=False,
    policy=None,
):

    policy = policy or current_policy()
    scored = []
    for candidate in candidates:
        mem_id = _memory_id(candidate)
        if not mem_id:
            scored.append({
                **candidate,
                "p_prov": None,
                "p_ground": None,
                "cheap_score": None,
                "passed_cheap_filter": False,
                "filter_reason": "non_memory_observation",
            })
            continue
        entry = state.get(mem_id)
        if entry is None:
            scored.append({
                **candidate,
                "p_prov": 0.0,
                "p_ground": 0.0,
                "cheap_score": 0.0,
                "passed_cheap_filter": False,
                "filter_reason": "memory_record_missing",
            })
            continue

        if oracle:
            p_prov, prov_basis = 1.0, ["oracle_context_trace"]
            p_ground = 1.0
            relation = candidate.get("relation", "action_necessity")
            supported_argument = candidate.get("supported_argument")
            grounding_basis = ["oracle_annotation"]
        else:
            p_prov, prov_basis = provenance_signal(
                candidate, entry, planner_context_memory_ids, action, rationale
            )
            p_ground, relation, supported_argument, grounding_basis = grounding_signal(
                candidate, entry, action, impact
            )
        cheap_score = _round(
            ATTR_WEIGHTS["provenance"] * p_prov
            + ATTR_WEIGHTS["grounding"] * p_ground
        )
        provenance_link = p_prov > 0.0


        grounding_link = oracle or any(
            basis.startswith("exact_") or basis.startswith("mutation_key_rule:")
            for basis in grounding_basis
        )
        if policy == "weighted":
            passed = oracle or (
                provenance_link and p_ground > 0.0 and cheap_score >= CHEAP_FILTER_THRESHOLD
            )
            pass_reason = "cheap_score_pass" if passed else "below_cheap_threshold"
        else:
            passed = oracle or (provenance_link and grounding_link)
            pass_reason = "staged_evidence_pass" if passed else "staged_evidence_missing"
        scored.append({
            **candidate,
            "memory_id": mem_id,
            "relation": relation,
            "supported_argument": supported_argument,
            "p_prov": p_prov,
            "provenance_basis": prov_basis,
            "p_ground": p_ground,
            "grounding_basis": grounding_basis,
            "cheap_score": cheap_score,
            "attribution_policy": policy,
            "provenance_link": provenance_link,
            "grounding_link": grounding_link,
            "passed_cheap_filter": passed,
            "filter_reason": "oracle_bypass" if oracle else (
                pass_reason
            ),
        })

    memory_candidates = [item for item in scored if item.get("memory_id")]
    selected = sorted(memory_candidates, key=lambda item: item["cheap_score"], reverse=True)
    selected = [item for item in selected if item["passed_cheap_filter"]]


    if not selected and memory_candidates and impact.get("impact_score", 0) >= 2:
        fallback = max(memory_candidates, key=lambda item: item["cheap_score"])
        fallback["passed_cheap_filter"] = True
        fallback["filter_reason"] = "high_risk_top1_fallback"
        selected = [fallback]

    selected_ids = {item["memory_id"] for item in selected[:MAX_CF_CANDIDATES]}
    for item in scored:
        if item.get("memory_id") and item["memory_id"] not in selected_ids and item["passed_cheap_filter"]:
            item["passed_cheap_filter"] = False
            item["filter_reason"] = "max_cf_candidates_cap"
    return scored


def selected_for_counterfactual(scored_candidates):
    return [item for item in scored_candidates if item.get("passed_cheap_filter")]


def counterfactual_delta(original_action, alternative_action, original_rationale="", alternative_rationale=""):

    original = action_model.normalize(original_action)
    alternative = action_model.normalize(alternative_action)
    signals = {
        "tool_changed": original.get("tool") != alternative.get("tool"),
        "operation_changed": original.get("operation") != alternative.get("operation"),
        "target_changed": original.get("target") != alternative.get("target"),
        "arguments_changed": original.get("arguments") != alternative.get("arguments"),
        "risk_changed": interceptor.classify(original)["impact_score"]
        != interceptor.classify(alternative)["impact_score"],
        "plan_changed": str(original_rationale or "").strip().lower()
        != str(alternative_rationale or "").strip().lower(),
    }
    severities = []
    if signals["tool_changed"] or signals["operation_changed"]:
        severities.append(1.0)
    if signals["target_changed"]:
        severities.append(0.90)
    if signals["arguments_changed"]:
        severities.append(0.80)
    if signals["risk_changed"]:
        severities.append(0.85)
    if signals["plan_changed"]:
        severities.append(0.25)
    return _round(max(severities, default=0.0)), signals


def finalize(scored_candidates, counterfactual_results, policy=None):

    policy = policy or current_policy()
    by_memory_id = {item.get("memory_id"): item for item in counterfactual_results}
    finalized = []
    for candidate in scored_candidates:
        mem_id = candidate.get("memory_id")
        cf = by_memory_id.get(mem_id)
        if cf:
            delta_cf = cf.get("delta_cf", 0.0)
            attr_score = _round(candidate["cheap_score"] + ATTR_WEIGHTS["counterfactual"] * delta_cf)
            changed = bool(cf.get("action_changed"))
            if policy == "weighted":
                critical = changed and attr_score >= FINAL_ATTR_THRESHOLD
                critical_basis = "weighted_threshold" if critical else "weighted_not_critical"
                robust_counterfactual = None
            else:
                robust_counterfactual = bool(
                    changed
                    and delta_cf >= STAGED_COUNTERFACTUAL_DELTA
                    and cf.get("counterfactual_stability", 0.0)
                    >= STAGED_COUNTERFACTUAL_STABILITY
                )
                evidence_chain = bool(
                    candidate.get("provenance_link")
                    and candidate.get("grounding_link")
                )
                high_risk_fail_safe = candidate.get("filter_reason") == "high_risk_top1_fallback"
                critical = robust_counterfactual and (evidence_chain or high_risk_fail_safe)
                critical_basis = (
                    "staged_evidence_contract" if critical and evidence_chain
                    else "staged_high_risk_fail_safe" if critical
                    else "staged_not_critical"
                )
            finalized.append({
                **candidate,
                **cf,
                "attr_score": attr_score,
                "attribution_policy": policy,
                "robust_counterfactual": robust_counterfactual,
                "critical_basis": critical_basis,
                "critical": critical,
                "counterfactual_tested": True,
            })
        else:
            finalized.append({
                **candidate,
                "delta_cf": None,
                "attr_score": candidate.get("cheap_score"),
                "attribution_policy": policy,
                "robust_counterfactual": False if policy == "staged" else None,
                "critical_basis": f"{policy}_not_counterfactually_tested",
                "critical": False,
                "counterfactual_tested": False,
            })
    return finalized


def stage_metrics(all_candidates, oracle_annotations):

    oracle_ids = {item["memory_id"] for item in oracle_annotations}

    def measure(ids):
        true_positive = len(ids & oracle_ids)
        precision = true_positive / len(ids) if ids else (1.0 if not oracle_ids else 0.0)
        recall = true_positive / len(oracle_ids) if oracle_ids else 1.0
        return {"precision": precision, "recall": recall, "memory_ids": sorted(ids)}

    candidate_ids = {item["memory_id"] for item in all_candidates if item.get("memory_id")}
    prefilter_ids = {
        item["memory_id"] for item in all_candidates
        if item.get("memory_id") and item.get("passed_cheap_filter")
    }
    final_ids = {
        item["memory_id"] for item in all_candidates
        if item.get("memory_id") and item.get("critical")
    }
    candidate = measure(candidate_ids)
    prefilter = measure(prefilter_ids)
    final = measure(final_ids)
    memory_count = len(candidate_ids)
    cf_candidate_count = sum(bool(item.get("counterfactual_tested")) for item in all_candidates)
    cf_probe_count = sum(
        int(item.get("counterfactual_interventions_tested", 0)) for item in all_candidates
    )
    return {


        "precision": final["precision"],
        "recall": final["recall"],
        "critical_state_miss_rate": 1.0 - final["recall"],
        "unsupported_state_rate": 1.0 - final["precision"],
        "candidate": candidate,
        "prefilter": prefilter,
        "final": final,
        "oracle_memory_ids": sorted(oracle_ids),
        "memory_candidate_count": memory_count,
        "counterfactual_candidate_count": cf_candidate_count,
        "counterfactual_probe_count": cf_probe_count,

        "counterfactual_call_count": cf_probe_count,
        "counterfactual_candidates_filtered": max(0, memory_count - cf_candidate_count),
        "counterfactual_calls_saved": max(0, memory_count - cf_candidate_count),
        "cheap_filter_false_negative_count": len(oracle_ids - prefilter_ids),
    }
