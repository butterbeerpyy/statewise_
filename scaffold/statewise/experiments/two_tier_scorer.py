from __future__ import annotations
from typing import List, Dict, Any, Optional

from scaffold.statewise.experiments.high_confidence_rules import (
    match_high_confidence_rule,
    get_rule_coverage_estimate
)


def two_tier_attribution(
    candidates: List[Dict],
    action: Dict,
    state: Dict,
    oracle: bool = False
) -> List[Dict]:


    tier1_results = []
    uncertain_candidates = []

    for candidate in candidates:
        rule_match = match_high_confidence_rule(candidate, action)

        if rule_match['matched'] and rule_match['confidence'] >= 0.85:

            tier1_results.append({
                'candidate': candidate,
                'score': rule_match['confidence'],
                'source': 'tier1_rule',
                'rule_name': rule_match.get('rule_name'),
                'attributed': True
            })
        else:

            uncertain_candidates.append(candidate)


    if len(tier1_results) >= 1:

        tier2_results = selective_fallback(uncertain_candidates, action, state)
    else:

        tier2_results = inclusive_fallback(uncertain_candidates, action, state)


    all_results = tier1_results + tier2_results


    filtered_results = apply_semantic_filters(all_results, action, state)

    return filtered_results


def selective_fallback(
    uncertain: List[Dict],
    action: Dict,
    state: Dict
) -> List[Dict]:

    results = []

    for candidate in uncertain:

        prov_score = compute_provenance(candidate, state)
        ground_score = compute_basic_grounding(candidate, action)


        if prov_score >= 0.6 and ground_score >= 0.5:
            combined_score = 0.5 * prov_score + 0.5 * ground_score

            results.append({
                'candidate': candidate,
                'score': min(0.75, combined_score),
                'source': 'tier2_selective',
                'attributed': True,
                'provenance': prov_score,
                'grounding': ground_score
            })

    return results


def inclusive_fallback(
    uncertain: List[Dict],
    action: Dict,
    state: Dict
) -> List[Dict]:

    results = []

    for candidate in uncertain:
        prov_score = compute_provenance(candidate, state)


        if prov_score >= 0.4:
            results.append({
                'candidate': candidate,
                'score': min(0.65, prov_score),
                'source': 'tier2_inclusive',
                'attributed': True,
                'provenance': prov_score
            })

    return results


def compute_provenance(candidate: Dict, state: Dict) -> float:

    memory_id = candidate.get('source', '').split(':', 1)[-1]


    if not memory_id:
        return 0.3


    return 0.6


def compute_basic_grounding(candidate: Dict, action: Dict) -> float:

    memory_str = str(candidate).lower()
    action_str = str(action).lower()


    action_keywords = set(action_str.split())
    memory_keywords = set(memory_str.split())


    overlap = len(action_keywords & memory_keywords)
    max_possible = max(len(action_keywords), 1)

    return min(1.0, overlap / max_possible)


def apply_semantic_filters(
    results: List[Dict],
    action: Dict,
    state: Dict
) -> List[Dict]:

    filtered = []

    for result in results:
        candidate = result['candidate']


        memory_str = str(candidate).lower()
        if any(decoy in memory_str for decoy in ['decoy', 'fake', 'misleading']):

            result['score'] *= 0.5
            result['decoy_detected'] = True


        if result['score'] >= 0.35:
            filtered.append(result)

    return filtered


def get_attribution_stats(results: List[Dict]) -> Dict[str, Any]:


    tier1_count = sum(1 for r in results if r.get('source') == 'tier1_rule')
    tier2_selective = sum(1 for r in results if r.get('source') == 'tier2_selective')
    tier2_inclusive = sum(1 for r in results if r.get('source') == 'tier2_inclusive')

    avg_score = sum(r['score'] for r in results) / len(results) if results else 0

    return {
        'total_attributed': len(results),
        'tier1_count': tier1_count,
        'tier2_selective_count': tier2_selective,
        'tier2_inclusive_count': tier2_inclusive,
        'avg_confidence': avg_score,
        'tier1_coverage': tier1_count / len(results) if results else 0
    }
