from datetime import datetime, timezone

from scaffold.statewise.memory import memory_store

_SOURCE_RELIABILITY = {
    "tool_verified": 0.95,


    "human_simulator_confirmed": 0.9,
    "user_confirmed": 0.9,
    "user_preference": 0.8,
    "historical_interaction": 0.55,
    "agent_inference": 0.35,
    "agent_summary": 0.3,
}


def _source_reliability(source):
    for prefix, score in _SOURCE_RELIABILITY.items():
        if source.startswith(prefix):
            return score
    return 0.4


def _parse_time(value):
    if not value or value == "current_session" or value.startswith("session-"):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _scopes_overlap(left, right):
    for key in set(left) | set(right):
        a, b = left.get(key, "*"), right.get(key, "*")
        if a != "*" and b != "*" and a != b:
            return False
    return True


def score(entry, state, current_scope=None, as_of=None):

    current_scope = current_scope or memory_store.DEFAULT_SCOPE

    src_rel = _source_reliability(entry["source"])

    confidence_factor = {"low": 0.3, "medium": 0.6, "high": 1.0}.get(
        entry.get("confidence", "medium"), 0.6
    )

    scope_match = 1.0
    entry_scope = entry.get("scope") or {}
    for k, v in current_scope.items():
        entry_v = entry_scope.get(k, "*")
        if entry_v not in ("*", v):
            scope_match = 0.2
            break

    conflicts = [
        other["id"]
        for other in memory_store.active_entries(state).values()
        if other["id"] != entry["id"]
        and other["key"] == entry["key"]
        and other["value"] != entry["value"]
        and _scopes_overlap(other.get("scope") or {}, entry_scope)
    ]
    conflict_penalty = 0.5 if conflicts else 1.0

    tool_verified = entry["source"].startswith("tool_verified")

    freshness_factor = 1.0
    age_days = None
    updated = _parse_time(entry.get("updated_at"))
    now = _parse_time(as_of) if isinstance(as_of, str) else as_of
    if updated and now:
        age_days = max(0.0, (now - updated).total_seconds() / 86400.0)
        ttl_days = entry.get("ttl_days")
        if ttl_days is not None and age_days > float(ttl_days):
            freshness_factor = 0.25
        elif age_days > 180:
            freshness_factor = 0.5
        elif age_days > 30:
            freshness_factor = 0.8

    reliability = src_rel * confidence_factor * scope_match * conflict_penalty * freshness_factor
    reliability = max(0.0, min(1.0, reliability))

    return {
        "reliability": reliability,
        "signals": {
            "source_reliability": src_rel,
            "confidence_factor": confidence_factor,
            "scope_match": scope_match,
            "conflicting_records": conflicts,
            "tool_verified": tool_verified,
            "freshness_factor": freshness_factor,
            "age_days": age_days,
            "ttl_days": entry.get("ttl_days"),
        },
    }
