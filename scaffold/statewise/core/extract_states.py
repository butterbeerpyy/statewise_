import re

from scaffold.statewise.agents import llm_client
from scaffold.statewise.core import interceptor
from scaffold.statewise.memory import memory_store


_RELEVANT_KEYS_BY_MUTATION = {
    "package_install": {"project_env", "dependency_install_allowed"},


    "environment_run": {"project_env"},
    "git_force_push": {"branch_is_protected", "current_branch"},
    "git_push": {"branch_is_protected", "current_branch"},
    "deploy": {"deploy_target"},
    "db_migrate": {"database_role"},
    "filesystem_delete": {"output_dir_status", "old_configs_usage_status"},
}


_KEY_FACETS_BY_MUTATION = {
    "package_install": {
        "env", "environment", "python", "runtime", "interpreter", "dependency",
        "package", "manager", "lock", "wheel", "backend", "driver", "version",
    },
    "environment_run": {
        "env", "environment", "python", "runtime", "interpreter", "dependency",
        "package", "manager", "backend", "driver", "version",
    },
    "git_force_push": {
        "git", "branch", "remote", "protected", "protection", "push", "force",
        "merge", "pull", "pr", "release", "freeze", "default",
    },
    "git_push": {
        "git", "branch", "remote", "protected", "protection", "push", "merge",
        "pull", "pr", "release", "freeze", "default",
    },
    "deploy": {
        "deploy", "deployment", "target", "environment", "cluster", "namespace",
        "region", "release", "production", "staging",
    },
    "db_migrate": {
        "db", "database", "role", "migration", "schema", "backup", "production",
        "staging", "target",
    },
    "filesystem_delete": {
        "file", "filesystem", "path", "dir", "directory", "output", "artifact",
        "cache", "snapshot", "generated", "archive", "retention", "backup", "log",
        "upload", "report", "checkpoint", "usage", "status", "golden", "baseline",
    },
    "filesystem_write": {
        "file", "filesystem", "path", "dir", "directory", "output", "artifact",
        "cache", "snapshot", "generated", "archive", "backup", "log", "upload",
        "report", "checkpoint", "status", "policy", "baseline",
    },
    "external_write": {
        "git", "branch", "remote", "protected", "protection", "push", "merge",
        "pull", "pr", "release", "freeze", "default", "target",
    },
}

_KEY_TOKEN_ALIASES = {
    "env": "environment",
    "dir": "directory",
    "fs": "filesystem",
    "db": "database",
    "pr": "pull",
}

_NON_OPERATIONAL_KEY_TOKENS = {"historical", "note", "comment", "description"}


def _tokens(value):

    raw = re.findall(r"[a-z0-9]+", str(value or "").lower())
    return {_KEY_TOKEN_ALIASES.get(token, token) for token in raw}


def _action_scalar_values(action):
    values = []

    def collect(value):
        if isinstance(value, dict):
            for nested in value.values():
                collect(nested)
        elif isinstance(value, (list, tuple, set)):
            for nested in value:
                collect(nested)
        elif value is not None and not isinstance(value, bool):
            values.append(str(value).strip().lower())

    collect(action.get("target"))
    collect(action.get("arguments", {}))
    return {value for value in values if value}


def _entry_relevant_to_action(entry, action, mutation_types, exact_keys):
    key = str(entry.get("key", ""))
    normalized_key = "_".join(sorted(_tokens(key)))
    if key in exact_keys or normalized_key in exact_keys:
        return True


    entry_value = entry.get("value")
    if not isinstance(entry_value, (dict, list, tuple, set)):
        rendered_value = str(entry_value).strip().lower()
        if rendered_value and rendered_value in _action_scalar_values(action):
            return True

    key_tokens = _tokens(key)
    if key_tokens & _NON_OPERATIONAL_KEY_TOKENS:
        return False
    relevant_facets = set()
    for mutation in mutation_types:
        relevant_facets.update(_KEY_FACETS_BY_MUTATION.get(mutation, set()))
    relevant_facets = {_KEY_TOKEN_ALIASES.get(token, token) for token in relevant_facets}
    return bool(key_tokens & relevant_facets)


def extract(
    action,
    state,
    case_id="default",
    stage_suffix="extract_states",
    scope=None,
):
    memory_text = memory_store.render_for_prompt(state, scope=scope)
    memory_ids = ", ".join(memory_store.active_entries(state, scope=scope).keys())
    messages = [
        {
            "role": "system",
            "content": (
                "Act as an independent argument Grounder. Given a proposed action "
                "and the persistent-memory candidates, list only records that ground "
                "the tool choice, target, an argument, or action necessity. You may "
                "also list a non-memory "
                "observation from this episode (e.g. an error message you just saw) "
                "if the action depends on it.\n\n"
                "Respond as JSON: {\"support_states\": [{\"id\": \"S1\", \"claim\": \"...\", "
                '"source": "...", "confidence": "low|medium|high", '
                '"relation": "used_to_choose_tool|used_to_fill_argument|action_necessity", '
                '"supported_argument": "target|path|branch|force|null"}]}\n\n'
                "Rules for `id`: always S1, S2, S3... (never reuse a memory id here).\n"
                f"Rules for `source`: if the state comes from persistent memory, it MUST be "
                f'exactly "memory:<id>" using one of these existing memory ids: {memory_ids}. '
                'If it is a fresh observation from this episode (not persistent memory), use '
                '"tool_observation" instead.'
            ),
        },
        {
            "role": "user",
            "content": f"Proposed action: {action}\n\nPersistent memory:\n{memory_text}",
        },
    ]
    result = llm_client.chat(f"{case_id}:{stage_suffix}", messages)
    active = memory_store.active_entries(state, scope=scope)
    declared = []
    for item in result["support_states"]:
        normalized = {**item, "grounder_declared": item.get("source", "").startswith("memory:")}
        source = normalized.get("source", "")
        if source.startswith("memory:") and source.split(":", 1)[1] not in active:


            claim_key = str(normalized.get("claim", "")).split("=", 1)[0].strip()
            replacement = memory_store.find_by_key(state, claim_key, scope=scope)
            if replacement is not None:
                normalized["source"] = f"memory:{replacement['id']}"
                normalized["source_rebound_from"] = source
        source = normalized.get("source", "")
        if source.startswith("memory:"):
            entry = active.get(source.split(":", 1)[1])
            claim_key = str(normalized.get("claim", "")).split("=", 1)[0].strip()


            if entry is None or claim_key != entry.get("key"):
                continue
        declared.append(normalized)


    deduplicated = []
    seen_memory_sources = set()
    for item in declared:
        source = item.get("source", "")
        if source.startswith("memory:"):
            if source in seen_memory_sources:
                continue
            seen_memory_sources.add(source)
        deduplicated.append(item)
    declared = deduplicated


    mutation_types = interceptor.classify(action)["mutation_types"]
    relevant_keys = set()
    for mutation in mutation_types:
        relevant_keys.update(_RELEVANT_KEYS_BY_MUTATION.get(mutation, set()))

    existing_sources = {item.get("source") for item in declared}
    next_index = 1 + max(
        [int(item["id"][1:]) for item in declared if item.get("id", "").startswith("S") and item["id"][1:].isdigit()]
        or [0]
    )
    augmented = list(declared)
    for entry in memory_store.active_entries(state, scope=scope).values():
        source = f"memory:{entry['id']}"
        if (
            not _entry_relevant_to_action(
                entry, action, mutation_types, relevant_keys
            )
            or source in existing_sources
        ):
            continue
        augmented.append({
            "id": f"S{next_index}",
            "claim": f"{entry['key']} = {entry['value']}",
            "source": source,
            "confidence": entry.get("confidence", "medium"),
            "candidate_origin": "retrieval_action_grounding",
            "grounder_declared": False,
        })
        next_index += 1


    has_memory_candidate = any(
        str(item.get("source", "")).startswith("memory:") for item in augmented
    )
    if mutation_types and not has_memory_candidate:
        for entry in memory_store.active_entries(state, scope=scope).values():
            source = f"memory:{entry['id']}"
            key_tokens = _tokens(entry.get("key"))
            if (
                source in existing_sources
                or str(entry.get("confidence", "medium")).lower() == "high"
                or key_tokens & _NON_OPERATIONAL_KEY_TOKENS
            ):
                continue
            augmented.append({
                "id": f"S{next_index}",
                "claim": f"{entry['key']} = {entry['value']}",
                "source": source,
                "confidence": entry.get("confidence", "medium"),
                "candidate_origin": "retrieval_uncertain_mutation_fallback",
                "grounder_declared": False,
            })
            next_index += 1
    return augmented


def from_oracle(case, state):

    support = []
    for index, annotation in enumerate(case.get("oracle_support_states", []), start=1):
        mem_id = annotation["memory_id"]
        entry = state.get(mem_id)
        if entry is None or entry.get("status", "active") != "active":
            entry = memory_store.find_by_key(
                state,
                case.get("memory_key"),
                scope=case.get("environment", {}).get("scope"),
            )
        if entry is None:
            continue
        support.append({
            "id": annotation.get("id", f"S{index}"),
            "claim": f"{entry['key']} = {entry['value']}",
            "source": f"memory:{entry['id']}",
            "confidence": entry.get("confidence", "medium"),
            "relation": annotation.get("relation", "action_necessity"),
            "supported_argument": annotation.get("supported_argument"),
            "candidate_origin": "oracle",
            "grounder_declared": False,
        })
    return support
