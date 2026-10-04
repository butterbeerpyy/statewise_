import json
import os

from scaffold.statewise import config

DEFAULT_SCOPE = {"repository": 'statewise', "branch": "*", "workspace": "*"}


def _default_state():
    return {
        "M1": {
            "id": "M1",
            "key": "project_env",
            "value": "base",
            "confidence": "low",
            "source": "agent_inference",
            "scope": dict(DEFAULT_SCOPE),
            "status": "active",
            "supersedes": [],
            "ttl_days": None,
            "evidence": None,
            "updated_at": "session-1",
        },
        "M2": {
            "id": "M2",
            "key": "historical_env_note",
            "value": "this repository previously used nightly",
            "confidence": "medium",
            "source": "historical_interaction",
            "scope": dict(DEFAULT_SCOPE),
            "status": "active",
            "supersedes": [],
            "ttl_days": None,
            "evidence": None,
            "updated_at": "session-1",
        },
        "M3": {
            "id": "M3",
            "key": "dependency_install_allowed",
            "value": True,
            "confidence": "high",
            "source": "user_preference",
            "scope": dict(DEFAULT_SCOPE),
            "status": "active",
            "supersedes": [],
            "ttl_days": None,
            "evidence": None,
            "updated_at": "session-1",
        },
    }


def default_state():

    return _default_state()


def load(path=None):
    path = path or config.MEMORY_STORE_PATH
    if not os.path.exists(path):
        return _default_state()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save(state, path=None):
    path = path or config.MEMORY_STORE_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def reset(path=None):

    state = _default_state()
    save(state, path)
    return state


def scope_matches(entry_scope, query_scope):

    if not query_scope:
        return True
    entry_scope = entry_scope or {}
    for field in ("repository", "branch", "workspace"):
        expected = query_scope.get(field)
        actual = entry_scope.get(field, "*")
        if expected in (None, "*") or actual == "*":
            continue
        if actual != expected:
            return False
    return True


def active_entries(state, scope=None):

    return {
        k: v
        for k, v in state.items()
        if v.get("status", "active") == "active"
        and scope_matches(v.get("scope"), scope)
    }


def find_by_key(state, key, scope=None):


    for entry in reversed(list(active_entries(state, scope=scope).values())):
        if entry["key"] == key:
            return entry
    return None


def render_for_prompt(state, scope=None):

    lines = []
    for entry in active_entries(state, scope=scope).values():
        lines.append(
            f"{entry['id']}: {entry['key']} = {entry['value']} "
            f"(confidence={entry['confidence']}, source={entry['source']}, "
            f"scope={entry.get('scope')}, updated_at={entry.get('updated_at')}, "
            f"ttl_days={entry.get('ttl_days')}, text={entry.get('text')!r})"
        )
    return "\n".join(lines)
