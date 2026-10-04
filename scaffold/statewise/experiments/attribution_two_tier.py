from __future__ import annotations

from contextlib import contextmanager
import hashlib
from pathlib import Path

from scaffold.statewise.core import attribution
from scaffold.statewise.experiments.two_tier_scorer import two_tier_attribution


VARIANTS = {
    "two_tier": "StateWise-v2+TwoTierRuleAttribution",
    "two_tier_reweighted": "StateWise-v2+TwoTierRuleAttribution+Reweighted",
}


WEIGHT_OVERRIDES = {
    "provenance": 0.35,
    "grounding": 0.50,
    "counterfactual": 0.15,
}
CHEAP_FILTER_THRESHOLD_OVERRIDE = 0.25
FINAL_ATTR_THRESHOLD_OVERRIDE = 0.50


TIER1_CONFIDENCE_FLOOR = 0.85


def method_name(variant):
    if variant not in VARIANTS:
        raise ValueError(f"unknown two-tier Attribution variant: {variant}")
    return VARIANTS[variant]


def method_fingerprint(variant):

    from scaffold.runners import method_freeze

    payload = (
        method_freeze.method_fingerprint().encode("utf-8")
        + b"\n"
        + method_name(variant).encode("utf-8")
        + b"\n"
        + Path(__file__).read_bytes()
    )
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _tier_annotations(result):

    return {
        "attributed_v2": True,
        "v2_source": result.get("source"),
        "v2_rule": result.get("rule_name"),
        "v2_tier_score": result.get("score"),
    }


def _score_wrapper(original):

    def wrapped(candidates, state, action, rationale, planner_context_memory_ids,
                impact, oracle=False, policy=None):
        scored = original(
            candidates,
            state,
            action,
            rationale,
            planner_context_memory_ids,
            impact,
            oracle=oracle,
            policy=policy,
        )
        if oracle:
            return scored

        try:
            tier_results = two_tier_attribution(
                candidates=candidates,
                action=action,
                state=state,
                oracle=oracle,
            )
        except Exception:


            return scored

        by_memory_id = {}
        for result in tier_results:
            memory_id = attribution._memory_id(result.get("candidate") or {})
            if memory_id:
                by_memory_id[memory_id] = result

        rescued = []
        for item in scored:
            memory_id = item.get("memory_id")
            if not memory_id or memory_id not in by_memory_id:
                continue
            result = by_memory_id[memory_id]
            item.update(_tier_annotations(result))
            if not item.get("passed_cheap_filter"):
                item["passed_cheap_filter"] = True
                item["filter_reason"] = (
                    "v2_tier1_rule_pass"
                    if result.get("source") == "tier1_rule"
                    else "v2_tier2_fallback_pass"
                )
                rescued.append(item)

        if not rescued:
            return scored


        selected = [item for item in scored if item.get("passed_cheap_filter")]
        selected.sort(
            key=lambda item: (
                -float(item.get("v2_tier_score") or item.get("cheap_score") or 0.0),
                str(item.get("memory_id") or ""),
            )
        )
        selected_ids = {
            item["memory_id"]
            for item in selected[: attribution.MAX_CF_CANDIDATES]
            if item.get("memory_id")
        }
        for item in scored:
            if (
                item.get("memory_id")
                and item["memory_id"] not in selected_ids
                and item.get("passed_cheap_filter")
            ):
                item["passed_cheap_filter"] = False
                item["filter_reason"] = "max_cf_candidates_cap"
        return scored

    return wrapped


@contextmanager
def use_variant(variant):

    method_name(variant)
    original_score = attribution.score_candidates
    original_weights = dict(attribution.ATTR_WEIGHTS)
    original_cheap = attribution.CHEAP_FILTER_THRESHOLD
    original_final = attribution.FINAL_ATTR_THRESHOLD
    try:
        attribution.score_candidates = _score_wrapper(original_score)
        if variant == "two_tier_reweighted":
            attribution.ATTR_WEIGHTS.update(WEIGHT_OVERRIDES)
            attribution.CHEAP_FILTER_THRESHOLD = CHEAP_FILTER_THRESHOLD_OVERRIDE
            attribution.FINAL_ATTR_THRESHOLD = FINAL_ATTR_THRESHOLD_OVERRIDE
        yield {
            "variant": variant,
            "method_name": method_name(variant),
            "method_fingerprint": method_fingerprint(variant),
        }
    finally:
        attribution.score_candidates = original_score
        attribution.ATTR_WEIGHTS.clear()
        attribution.ATTR_WEIGHTS.update(original_weights)
        attribution.CHEAP_FILTER_THRESHOLD = original_cheap
        attribution.FINAL_ATTR_THRESHOLD = original_final
