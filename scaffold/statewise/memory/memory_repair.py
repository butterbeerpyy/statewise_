from scaffold.statewise.memory import memory_store


def repair(state, key, value, source, confidence, evidence, scope=None, supersede_id=None):

    scope = scope or dict(memory_store.DEFAULT_SCOPE)
    supersedes = []
    scope_fields = ("repository", "branch", "workspace")
    for entry in state.values():
        if entry.get("status", "active") != "active" or entry.get("key") != key:
            continue
        entry_scope = entry.get("scope") or dict(memory_store.DEFAULT_SCOPE)
        same_scope = all(
            entry_scope.get(field, "*") == scope.get(field, "*")
            for field in scope_fields
        )
        if entry.get("id") == supersede_id or same_scope:
            entry["status"] = "deprecated"
            supersedes.append(entry["id"])

    new_id = _next_id(state)
    state[new_id] = {
        "id": new_id,
        "key": key,
        "value": value,
        "confidence": confidence,
        "source": source,
        "scope": scope,
        "status": "active",
        "supersedes": sorted(supersedes),
        "ttl_days": None,
        "evidence": evidence,
        "updated_at": "current_session",
    }
    return new_id


def _next_id(state):
    n = 1
    while f"M{n}" in state:
        n += 1
    return f"M{n}"
