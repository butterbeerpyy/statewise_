from __future__ import annotations

from contextlib import contextmanager
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

from scaffold.statewise.core import (
    action_model,
    attribution,
    critical_detect,
    extract_states,
    interceptor,
)
from scaffold.statewise.memory import memory_store


STATEWISE_V1_FINGERPRINT = (
    "sha256:2c425f065f242dfbff33ffd1c47119fd69c512e5e6e8a52550ac1c4fe25e0f44"
)
VARIANTS = {
    "v1": "StateWise-v1",
    "semantic_recall": "StateWise-v2+SemanticCandidateRecall",
    "retrieval": "StateWise-v2+DecisionAwareRetrieval",
    "retrieval_graph": "StateWise-v2+DecisionAwareRetrieval+MemoryGraph",
    "retrieval_slots": "StateWise-v2+SlotAwareRetrieval",
    "retrieval_conflict": "StateWise-v2+ConflictAwareRetrieval",
    "retrieval_slots_conflict": (
        "StateWise-v2+SlotAwareRetrieval+ConflictAwareFiltering"
    ),
}
MAX_AUGMENTED_CANDIDATES = 3
MIN_SEMANTIC_SCORE = 0.30

MAX_RETRIEVAL_CANDIDATES = 8
MAX_RETRIEVAL_CF_PROBES = 4


MAX_RETRIEVAL_CF_INTERVENTIONS = 3
MIN_RETRIEVAL_SCORE = 0.16
MIN_GRAPH_SEED_SCORE = 0.24
MIN_ROBUST_CF_DELTA = 0.50
MIN_ROBUST_CF_STABILITY = 0.50


_ACTION_KEY_HINTS = {
    ("filesystem", "delete"): {
        "artifact", "audit", "backup", "bundle", "cache", "evidence", "hold",
        "log", "output", "policy", "report", "retention", "site", "snapshot",
        "status", "usage",
    },
    ("filesystem", "archive"): {
        "artifact", "audit", "backup", "bundle", "cache", "evidence", "hold",
        "log", "output", "policy", "report", "retention", "snapshot", "status",
    },
    ("git", "force_push"): {
        "branch", "diverged", "emergency", "force", "freeze", "override",
        "policy", "protect", "protected", "release", "remote",
    },
    ("git", "push"): {
        "branch", "diverged", "emergency", "force", "freeze", "override",
        "policy", "protect", "protected", "release", "remote",
    },
    ("git", "open_pull_request"): {
        "base", "branch", "default", "policy", "pr", "protect", "protected",
        "release", "target",
    },
    ("package_manager", "install"): {
        "backend", "dependency", "deploy", "environment", "matrix", "package",
        "project", "python", "runtime", "scope",
    },
    ("environment", "run_python"): {
        "backend", "compat", "dependency", "deploy", "environment", "matrix",
        "package", "project", "python", "runtime", "scope",
    },
    ("environment", "inspect_package"): {
        "dependency", "environment", "package", "project", "python", "runtime",
    },
}

_GRAPH_GENERIC_TOKENS = {
    "action", "active", "allowed", "artifact", "branch", "current",
    "default", "environment", "false", "file", "memory", "output", "path",
    "policy", "project", "repository", "state", "status", "target", "true",
    "unknown", "value",
}

_INCOMPATIBLE_PREFIXES = {
    "doc", "docs", "documentation", "example", "guide", "historical", "readme",
    "sample", "tutorial",
}
_GENERIC_STATE_TOKENS = {
    "active", "allowed", "artifact", "branch", "current", "dir", "directory",
    "environment", "env", "file", "output", "path", "project", "repository",
    "state", "status", "target", "value",
}
_TARGET_FAMILY_TOKENS = {
    "artifact", "branch", "checkpoint", "config", "environment", "env",
    "output", "report", "site",
}
_STATE_FACETS = {
    ("filesystem", "delete"): {
        "target_state": {
            "artifact", "audit", "backup", "bundle", "cache", "checkpoint",
            "config", "dump", "evidence", "log", "output", "report", "site",
            "snapshot", "status", "usage",
        },
        "safety_constraint": {
            "active", "approval", "authorized", "hold", "job", "owner",
            "permission", "policy", "replica", "replication", "retention",
            "signoff",
        },
    },
    ("package_manager", "install"): {
        "environment": {
            "backend", "environment", "env", "project", "python", "runtime",
        },
        "execution_scope": {
            "allowed", "dependency", "install", "matrix", "release", "scope",
            "test",
        },
    },
    ("environment", "run_python"): {
        "environment": {
            "backend", "environment", "env", "project", "python", "runtime",
        },
        "execution_scope": {
            "compat", "dependency", "matrix", "release", "scope", "test",
        },
    },
    ("git", "force_push"): {
        "branch_policy": {
            "branch", "freeze", "policy", "protect", "protected", "protection",
        },
        "divergence": {"diverged", "divergence", "remote"},
        "override": {"authorization", "emergency", "override", "permission"},
    },
    ("git", "push"): {
        "branch_policy": {
            "branch", "freeze", "policy", "protect", "protected", "protection",
        },
        "divergence": {"diverged", "divergence", "remote"},
    },
    ("git", "open_pull_request"): {
        "target_selection": {
            "base", "branch", "default", "pr", "release", "target",
        },
        "safety_constraint": {
            "freeze", "policy", "protect", "protected", "protection",
        },
    },
    ("deployment", "deploy"): {
        "environment": {"deploy", "deployment", "environment", "region", "target"},
        "safety_constraint": {
            "approval", "authorized", "freeze", "owner", "permission", "policy",
        },
    },
    ("database", "migrate"): {
        "environment": {"database", "environment", "production", "role", "target"},
        "safety_constraint": {
            "approval", "authorized", "backup", "permission", "policy",
        },
    },
}
_REQUIRED_FACETS = {
    ("filesystem", "delete"): {"target_state", "safety_constraint"},
    ("package_manager", "install"): {"environment", "execution_scope"},
    ("environment", "run_python"): {"environment", "execution_scope"},
    ("git", "force_push"): {"branch_policy", "divergence", "override"},
    ("git", "push"): {"branch_policy", "divergence"},
    ("git", "open_pull_request"): {"target_selection"},
    ("deployment", "deploy"): {"environment", "safety_constraint"},
    ("database", "migrate"): {"environment", "safety_constraint"},
}


_ACTION_STATE_SLOTS = {
    ("package_manager", "install"): {
        "environment": {
            "environment", "env", "project", "python", "runtime",
        },
        "backend_compatibility": {
            "backend", "compat", "cuda", "driver", "gpu", "requirement",
        },
        "package_target": {
            "artifact", "manylinux", "package", "target", "wheel",
        },
        "execution_scope": {
            "allowed", "install", "matrix", "release", "scope", "test",
        },
    },
    ("environment", "run_python"): {
        "environment": {
            "environment", "env", "project", "python", "runtime",
        },
        "backend_compatibility": {
            "backend", "compat", "cuda", "driver", "gpu", "requirement",
        },
        "execution_target": {
            "script", "target", "test", "wheel",
        },
        "execution_scope": {
            "allowed", "matrix", "release", "scope",
        },
    },
    ("filesystem", "delete"): {
        "target_state": {
            "artifact", "bundle", "checkpoint", "config", "directory", "dir",
            "evidence", "generation", "output", "path", "report", "site",
            "snapshot", "status",
        },
        "dependency_usage": {
            "active", "deploy", "deployment", "enabled", "generation", "job",
            "reference", "referenced", "usage", "use",
        },
        "protection_constraint": {
            "approval", "attachment", "audit", "hold", "owner", "permission",
            "policy", "release", "replica", "replication", "retention",
            "signoff", "ticket", "trace",
        },
    },
    ("filesystem", "archive"): {
        "target_state": {
            "artifact", "bundle", "checkpoint", "directory", "dir", "evidence",
            "generation", "output", "path", "report", "snapshot", "status",
        },
        "dependency_usage": {
            "active", "deploy", "enabled", "job", "reference", "usage", "use",
        },
        "protection_constraint": {
            "audit", "hold", "owner", "permission", "policy", "release",
            "replica", "retention", "ticket", "trace",
        },
    },
    ("git", "force_push"): {
        "branch_policy": {
            "branch", "freeze", "policy", "protect", "protected", "requires",
            "review",
        },
        "divergence": {
            "diverged", "divergence", "local", "remote", "rebase",
        },
        "workflow_override": {
            "authorization", "emergency", "force", "hotfix", "override",
            "permission", "rollout", "trunk", "workflow",
        },
    },
    ("git", "push"): {
        "branch_policy": {
            "branch", "freeze", "policy", "protect", "protected", "requires",
            "review",
        },
        "divergence": {
            "diverged", "divergence", "local", "remote", "rebase",
        },
        "workflow_override": {
            "hotfix", "rollout", "trunk", "workflow",
        },
    },
    ("git", "open_pull_request"): {
        "target_selection": {
            "base", "branch", "default", "pr", "release", "target",
        },
        "branch_policy": {
            "freeze", "policy", "protect", "protected", "requires", "review",
        },
        "workflow": {
            "hotfix", "rollout", "trunk", "workflow",
        },
    },
    ("deployment", "deploy"): {
        "deployment_target": {
            "deploy", "deployment", "environment", "region", "service",
            "target",
        },
        "release_version": {
            "artifact", "release", "revision", "sha", "version",
        },
        "backend_compatibility": {
            "backend", "compat", "dependency", "requirement", "runtime",
        },
        "protection_constraint": {
            "approval", "authorized", "freeze", "owner", "permission",
            "policy",
        },
    },
    ("database", "migrate"): {
        "database_target": {
            "database", "environment", "production", "role", "target",
        },
        "migration_version": {
            "head", "migration", "revision", "version",
        },
        "protection_constraint": {
            "approval", "authorized", "backup", "owner", "permission",
            "policy",
        },
    },
}

_CONSEQUENTIAL_ARGUMENTS = {
    "base", "branch", "environment", "migration", "package", "path", "region",
    "release", "service", "target", "version",
}


_SIBLING_RESOURCE_TOKENS = {
    "cache", "doc", "docs", "example", "history", "historical", "log", "logs",
    "sample", "session", "stat", "statistics", "tutorial",
}


def method_name(variant):
    if variant not in VARIANTS:
        raise ValueError(f"unknown Attribution-v2 variant: {variant}")
    return VARIANTS[variant]


def method_fingerprint(variant):
    payload = (
        STATEWISE_V1_FINGERPRINT.encode("utf-8")
        + b"\n"
        + method_name(variant).encode("utf-8")
        + b"\n"
        + Path(__file__).read_bytes()
    )
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _tokens(value):
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(value).lower().replace("_", " "))
        if len(token) >= 2
        and token
        not in {
            "a", "an", "and", "current", "default", "false", "none", "only",
            "the", "this", "true", "unknown",
        }
    }


def _normalized_tokens(value):
    return {
        (
            token[:-1]
            if token.endswith("s")
            and len(token) > 3


            and token not in {"analysis", "class", "process", "status"}
            else token
        )
        for token in _tokens(value)
    }


def _tool_operation(action):
    normalized = action_model.normalize(action)
    return normalized.get("tool"), normalized.get("operation")


def _entry_facets(entry, action):
    key_tokens = _normalized_tokens(entry.get("key", ""))
    facets = set()
    operation_facets = _STATE_FACETS.get(_tool_operation(action), {})
    for facet, vocabulary in operation_facets.items():
        if key_tokens & vocabulary:
            facets.add(facet)


    value_tokens = _normalized_tokens(entry.get("value", ""))
    action_tokens = _normalized_tokens(json.dumps(
        action_model.normalize(action), ensure_ascii=False, sort_keys=True
    ))
    if (
        operation_facets
        and value_tokens
        and value_tokens <= action_tokens
        and value_tokens
        not in ({"true"}, {"false"}, {"none"}, {"unknown"})
    ):
        facets.add("target_binding")
    return facets


def action_state_slots(action):

    normalized = action_model.normalize(action)
    slots = {
        name: set(vocabulary)
        for name, vocabulary in _ACTION_STATE_SLOTS.get(
            (normalized.get("tool"), normalized.get("operation")),
            {},
        ).items()
    }
    arguments = normalized.get("arguments") or {}
    for name, value in arguments.items():
        if (
            name not in _CONSEQUENTIAL_ARGUMENTS
            or value in (None, "", False)
        ):
            continue
        tokens = _normalized_tokens(name)
        tokens.update(_normalized_tokens(value))
        slots[f"argument:{name}"] = tokens
    target = normalized.get("target")
    if target not in (None, ""):
        tokens = _normalized_tokens("target")
        tokens.update(_normalized_tokens(target))
        slots["argument:target"] = tokens
    return slots


def _entry_slots(entry, action, facets=None):

    facets = set(facets or ())
    key_tokens = _normalized_tokens(entry.get("key", ""))
    value_tokens = _normalized_tokens(entry.get("value", ""))
    entry_tokens = key_tokens | value_tokens
    matched = set()
    for slot, vocabulary in action_state_slots(action).items():
        overlap = entry_tokens & vocabulary
        if not overlap:
            continue
        if (
            slot == "branch_policy"
            and overlap <= {"requires", "review"}
            and not key_tokens
            & {"branch", "freeze", "policy", "protect", "protected"}
        ):
            continue
        if (
            slot == "divergence"
            and overlap <= {"local", "rebase"}
            and not key_tokens & {"diverged", "divergence", "remote"}
        ):
            continue
        if slot.startswith("argument:"):


            argument = slot.split(":", 1)[1]
            argument_tokens = _normalized_tokens(argument)
            concrete_tokens = vocabulary - argument_tokens
            if not (
                key_tokens & argument_tokens
                or (concrete_tokens and entry_tokens & concrete_tokens)
            ):
                continue
        matched.add(slot)


    for facet in facets:
        if facet in action_state_slots(action):
            matched.add(facet)
    return matched


def _action_retrieval_scopes(scope, action, *, slot_aware=False):

    scope = dict(scope or {})
    scopes = [scope]
    if not slot_aware:
        return scopes
    normalized = action_model.normalize(action)
    if normalized.get("tool") != "git":
        return scopes
    arguments = normalized.get("arguments") or {}
    target_branches = [
        normalized.get("target"),
        arguments.get("branch"),
        arguments.get("base"),
        arguments.get("target"),
    ]
    for branch in target_branches:
        if branch in (None, "", True, False):
            continue
        query = dict(scope)
        query["branch"] = branch
        if query not in scopes:
            scopes.append(query)
    return scopes


def _active_retrieval_entries(state, scope, action, *, slot_aware=False):
    entries = memory_store.active_entries(state)
    scopes = _action_retrieval_scopes(scope, action, slot_aware=slot_aware)
    return [
        entry
        for entry in entries.values()
        if any(
            memory_store.scope_matches(entry.get("scope"), query)
            for query in scopes
        )
    ]


def _target_tokens(action):
    normalized = action_model.normalize(action)
    arguments = normalized.get("arguments", {})
    values = [
        normalized.get("target"),
        arguments.get("path"),
        arguments.get("branch"),
        arguments.get("environment"),
        arguments.get("service"),
        arguments.get("target"),
    ]
    result = set()
    for value in values:
        if value not in (None, ""):
            result.update(_normalized_tokens(value))


    return result - {"configured", "current", "path", "target"}


def _action_binding_strength(entry, action, slots):

    normalized = action_model.normalize(action)
    action_text = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True
    ).lower()
    value_text = str(entry.get("value", "")).strip().lower()
    key_tokens = _normalized_tokens(entry.get("key", ""))
    action_target = _target_tokens(action)
    value_tokens = _normalized_tokens(entry.get("value", ""))
    if (
        value_text not in {"", "true", "false", "none", "unknown"}
        and value_text in action_text
    ):
        return 4
    if value_tokens and value_tokens <= action_target:
        return 4
    if action_target & (key_tokens - _GENERIC_STATE_TOKENS):
        return 3
    if any(slot.startswith("argument:") for slot in slots):
        return 3
    if slots:
        return 2
    return 1


def _canonical_entry_value(entry):
    return json.dumps(
        entry.get("value"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).lower()


def _scope_identity(entry):
    scope = entry.get("scope") or {}
    return tuple(
        str(scope.get(field, "*"))
        for field in ("repository", "branch", "workspace")
    )


def _representative_order(entry, action, slots):
    rank = int(entry.get("retrieval_rank") or 1_000_000)
    return (
        -_action_binding_strength(entry, action, slots),
        rank,
        -_direct_provenance_priority(entry),
        str(entry.get("id")),
    )


def _conflict_filter_entries(entries, action, facets_by_id, slots_by_id):

    by_key_scope = {}
    for entry in entries:
        identity = (
            str(entry.get("key", "")).strip().lower(),
            _scope_identity(entry),
        )
        by_key_scope.setdefault(identity, []).append(entry)

    suppressed = {}
    conflict_meta = {}
    for (key, scope_identity), group in by_key_scope.items():
        conflict_id = "key:" + hashlib.sha256(
            json.dumps(
                [key, scope_identity],
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:12]
        by_value = {}
        for entry in group:
            by_value.setdefault(_canonical_entry_value(entry), []).append(entry)
        representatives = []
        for duplicates in by_value.values():
            ordered = sorted(
                duplicates,
                key=lambda item: _representative_order(
                    item,
                    action,
                    slots_by_id.get(item["id"], set()),
                ),
            )
            representatives.append(ordered[0])
            for duplicate in ordered[1:]:
                suppressed[duplicate["id"]] = (
                    f"duplicate_claim_represented_by:{ordered[0]['id']}"
                )

        if len(representatives) > 1:
            strengths = {
                item["id"]: _action_binding_strength(
                    item,
                    action,
                    slots_by_id.get(item["id"], set()),
                )
                for item in representatives
            }
            maximum = max(strengths.values())
            strongest = [
                memory_id
                for memory_id, strength in strengths.items()
                if strength == maximum
            ]


            if maximum >= 4 and len(strongest) == 1:
                for item in representatives:
                    if item["id"] != strongest[0]:
                        suppressed[item["id"]] = (
                            f"conflict_value_not_bound_to_action:{strongest[0]}"
                        )

        competing = sorted(item["id"] for item in group)
        for entry in group:
            conflict_meta[entry["id"]] = {
                "conflict_set_id": conflict_id,
                "competing_memory_ids": [
                    memory_id
                    for memory_id in competing
                    if memory_id != entry["id"]
                ],
            }

    action_target = _target_tokens(action)
    target_state_entries = [
        entry
        for entry in entries
        if entry["id"] not in suppressed
        and "target_state" in slots_by_id.get(entry["id"], set())
    ]
    for entry in entries:
        if entry["id"] in suppressed:
            continue
        slots = slots_by_id.get(entry["id"], set())
        if "target_state" not in slots:
            continue
        key_tokens = _normalized_tokens(entry.get("key", ""))
        sibling = (key_tokens & _SIBLING_RESOURCE_TOKENS) - action_target
        if sibling and any(
            other["id"] != entry["id"]
            and not (
                _normalized_tokens(other.get("key", ""))
                & _SIBLING_RESOURCE_TOKENS
                - action_target
            )
            and _action_binding_strength(
                other,
                action,
                slots_by_id.get(other["id"], set()),
            )
            >= _action_binding_strength(entry, action, slots)
            for other in target_state_entries
        ):
            suppressed[entry["id"]] = (
                "sibling_resource_not_named_by_action:"
                + ",".join(sorted(sibling))
            )

    return (
        [entry for entry in entries if entry["id"] not in suppressed],
        suppressed,
        conflict_meta,
    )


def _target_relation(entry, action, facets):

    normalized = action_model.normalize(action)
    action_target = _target_tokens(action)
    key_tokens = _normalized_tokens(entry.get("key", ""))
    if key_tokens & _INCOMPATIBLE_PREFIXES and not (
        action_target & _INCOMPATIBLE_PREFIXES
    ):
        return 0, "incompatible_state_namespace"
    action_text = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True
    ).lower()
    value_text = str(entry.get("value", "")).strip().lower()
    if (
        value_text not in {"", "true", "false", "none", "unknown"}
        and value_text in action_text
    ):
        return 3, "exact_value_in_action"
    value_tokens = _normalized_tokens(entry.get("value", ""))
    if (
        value_tokens
        and value_tokens <= action_target
        and value_tokens
        not in ({"true"}, {"false"}, {"none"}, {"unknown"})
    ):
        return 3, "normalized_value_matches_target"
    if facets & {"safety_constraint", "execution_scope", "branch_policy", "divergence", "override"}:
        return 1, "global_action_constraint"

    entry_entities = key_tokens - _GENERIC_STATE_TOKENS
    if not action_target or not entry_entities:
        return 1, "generic_target_state"
    overlap = action_target & entry_entities
    if not overlap:
        return 0, "clearly_unrelated_target"
    left_only = action_target - overlap
    right_only = entry_entities - overlap
    if (
        overlap <= _TARGET_FAMILY_TOKENS
        and left_only
        and right_only
    ):
        return 0, "conflicting_target_sibling"
    return 2, "target_token_match"


def _exact_scope_score(entry, scope):
    if not scope:
        return 0
    entry_scope = entry.get("scope") or {}
    return sum(
        entry_scope.get(field) == scope.get(field)
        for field in ("repository", "workspace")
        if scope.get(field) not in (None, "*")
    )


def _direct_provenance_priority(entry):

    source = str(entry.get("source") or "").lower()
    if source in {
        "human", "tool_observation", "runtime_observation", "verified_fixture",
    }:
        return 2
    if entry.get("evidence") not in (None, "", [], {}):
        return 1
    return 0


def _rescue_trigger(candidates, state, action, scope):

    entries = memory_store.active_entries(state, scope=scope)
    candidate_entries = []
    reasons = []
    for candidate in candidates:
        source = str(candidate.get("source") or "")
        if not source.startswith("memory:"):
            continue
        entry = entries.get(source.split(":", 1)[1])
        if entry is None:
            reasons.append("v1_candidate_scope_mismatch")
        else:
            candidate_entries.append(entry)
    if not candidate_entries:
        reasons.append("v1_candidate_empty")

    covered_facets = set()
    target_covered = False
    for entry in candidate_entries:
        facets = _entry_facets(entry, action)
        covered_facets.update(facets)
        relation, _ = _target_relation(entry, action, facets)
        target_covered = target_covered or relation >= 2
    if _target_tokens(action) and not target_covered:
        reasons.append("v1_target_not_covered")
    missing = _REQUIRED_FACETS.get(_tool_operation(action), set()) - covered_facets
    if missing:
        reasons.append("v1_missing_facets:" + ",".join(sorted(missing)))
    return list(dict.fromkeys(reasons))


def _rescue_action_allowed(action):
    impact = interceptor.classify(action)
    if impact.get("is_read_only"):
        return False
    if _tool_operation(action) == ("git", "open_pull_request"):
        return True
    return bool(
        impact.get("impact_score", 0) >= 2
        or set(impact.get("mutation_types", []))
        & {
            "package_install", "environment_run", "git_force_push", "git_push",
            "deploy", "db_migrate",
        }
    )


def semantic_candidate_score(entry, action):

    normalized = action_model.normalize(action)
    tool_operation = (normalized["tool"], normalized["operation"])
    action_text = json.dumps(normalized, ensure_ascii=False, sort_keys=True).lower()
    action_tokens = _tokens(action_text)
    key_tokens = _tokens(entry.get("key", ""))
    value = entry.get("value")
    value_text = str(value).strip().lower()
    score = 0.0
    basis = []

    if (
        isinstance(value, str)
        and len(value_text) >= 2
        and value_text not in {"true", "false", "none", "unknown"}
        and value_text in action_text
    ):
        score += 0.70
        basis.append("exact_memory_value_in_action")

    overlap = key_tokens & action_tokens
    if overlap:
        ratio = len(overlap) / max(1, len(key_tokens))
        score += min(0.45, 0.15 + 0.45 * ratio)
        basis.append(f"memory_key_action_overlap:{','.join(sorted(overlap))}")

    hint_overlap = key_tokens & _ACTION_KEY_HINTS.get(tool_operation, set())
    if hint_overlap:
        score += min(0.45, 0.20 + 0.10 * len(hint_overlap))
        basis.append(f"action_class_key_hint:{','.join(sorted(hint_overlap))}")

    return min(1.0, round(score, 4)), basis


def _entry_tokens(entry):

    tokens = set()
    for field in ("key", "value", "text", "evidence"):
        value = entry.get(field)
        if value is not None:
            tokens.update(_tokens(json.dumps(value, ensure_ascii=False)))
    return list(tokens)


def _expanded_action_tokens(action):
    normalized = action_model.normalize(action)
    result = set(_tokens(json.dumps(normalized, ensure_ascii=False, sort_keys=True)))
    result.update(
        _ACTION_KEY_HINTS.get(
            (normalized.get("tool"), normalized.get("operation")),
            set(),
        )
    )
    return result


def _bm25_scores(entries, action):

    documents = {entry["id"]: _entry_tokens(entry) for entry in entries}
    if not documents:
        return {}
    query = _expanded_action_tokens(action)
    document_frequency = Counter()
    for tokens in documents.values():
        document_frequency.update(set(tokens))
    document_count = len(documents)
    average_length = sum(map(len, documents.values())) / max(1, document_count)
    raw = {}
    for memory_id, tokens in documents.items():
        frequencies = Counter(tokens)
        length = len(tokens)
        score = 0.0
        for token in query:
            frequency = frequencies[token]
            if not frequency:
                continue
            df = document_frequency[token]
            inverse_document_frequency = math.log(
                1.0 + (document_count - df + 0.5) / (df + 0.5)
            )
            denominator = frequency + 1.2 * (
                1.0 - 0.75
                + 0.75 * length / max(1.0, average_length)
            )
            score += inverse_document_frequency * (
                frequency * 2.2 / denominator
            )
        raw[memory_id] = score
    maximum = max(raw.values(), default=0.0)
    if maximum <= 0.0:
        return {memory_id: 0.0 for memory_id in raw}
    return {
        memory_id: round(score / maximum, 4)
        for memory_id, score in raw.items()
    }


def _explicit_neighbor_ids(entry):
    ids = set()
    for field in (
        "supersedes",
        "conflicts_with",
        "derived_from",
        "verified_by",
        "related_memory_ids",
    ):
        value = entry.get(field)
        if isinstance(value, str):
            ids.add(value)
        elif isinstance(value, (list, tuple, set)):
            ids.update(str(item) for item in value)
    relations = entry.get("relations")
    if isinstance(relations, dict):
        values = relations.values()
    elif isinstance(relations, list):
        values = relations
    else:
        values = ()
    for value in values:
        if isinstance(value, str):
            ids.add(value)
        elif isinstance(value, dict):
            target = value.get("memory_id") or value.get("target")
            if target:
                ids.add(str(target))
    return ids


def _graph_relation(left, right):

    if right["id"] in _explicit_neighbor_ids(left):
        return "explicit_memory_edge"
    if left["id"] in _explicit_neighbor_ids(right):
        return "reverse_explicit_memory_edge"
    return None


def _slot_stratified_ranked(ranked, action):

    selected = []
    selected_ids = set()
    for slot in action_state_slots(action):
        match = next(
            (
                item
                for item in ranked
                if slot in item[6] and item[2]["id"] not in selected_ids
            ),
            None,
        )
        if match is None:
            continue
        selected.append(match)
        selected_ids.add(match[2]["id"])
        if len(selected) >= MAX_RETRIEVAL_CANDIDATES:
            return selected
    for item in ranked:
        if item[2]["id"] in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(item[2]["id"])
        if len(selected) >= MAX_RETRIEVAL_CANDIDATES:
            break
    return selected


def retrieve_candidates(
    candidates,
    action,
    state,
    scope=None,
    graph=False,
    slot_aware=False,
    conflict_aware=False,
):

    augmented = [dict(item) for item in candidates]
    trigger_reasons = _rescue_trigger(augmented, state, action, scope)
    if not trigger_reasons or not _rescue_action_allowed(action):
        return augmented
    entries = _active_retrieval_entries(
        state,
        scope,
        action,
        slot_aware=slot_aware,
    )
    facets_by_id = {
        entry["id"]: _entry_facets(entry, action)
        for entry in entries
    }
    slots_by_id = {
        entry["id"]: _entry_slots(
            entry,
            action,
            facets_by_id[entry["id"]],
        )
        for entry in entries
    }
    suppressed = {}
    conflict_meta = {}
    if conflict_aware:
        entries, suppressed, conflict_meta = _conflict_filter_entries(
            entries,
            action,
            facets_by_id,
            slots_by_id,
        )


        augmented = [
            item
            for item in augmented
            if not (
                str(item.get("source") or "").startswith("memory:")
                and str(item["source"]).split(":", 1)[1] in suppressed
            )
        ]
    existing_sources = {item.get("source") for item in augmented}
    by_id = {entry["id"]: entry for entry in entries}
    bm25 = _bm25_scores(entries, action)
    ranked = []
    direct_scores = {}
    direct_basis = {}
    for entry in entries:
        facets = facets_by_id[entry["id"]]
        slots = slots_by_id[entry["id"]]
        if not facets and not (slot_aware and slots):
            continue
        target_relation, target_basis = _target_relation(entry, action, facets)
        if (
            target_relation <= 0
            and slot_aware
            and slots
            and target_basis not in {
                "incompatible_state_namespace",
                "conflicting_target_sibling",
            }
        ):


            if any(
                not slot.startswith("argument:")
                for slot in slots
            ):
                target_relation = 1
                target_basis = "required_state_slot_constraint"
        if target_relation <= 0:
            continue
        structured, structured_basis = semantic_candidate_score(entry, action)
        lexical = bm25.get(entry["id"], 0.0)
        semantic_rank = round(0.65 * structured + 0.35 * lexical, 4)


        score = max(MIN_RETRIEVAL_SCORE, semantic_rank)
        exact_scope = _exact_scope_score(entry, scope)
        provenance_priority = _direct_provenance_priority(entry)
        priority = (
            target_relation * 1_000
            + exact_scope * 100
            + provenance_priority * 10
            + len(slots) * 3
            + len(facets) * 2
            + semantic_rank
        )
        basis = [
            f"rescue_trigger:{item}" for item in trigger_reasons
        ]
        basis.extend(f"structured:{item}" for item in structured_basis)
        basis.extend([
            f"hard_filter_target:{target_basis}",
            f"hard_filter_facets:{','.join(sorted(facets))}",
            f"state_contract_slots:{','.join(sorted(slots))}",
            f"exact_scope_fields:{exact_scope}",
            f"direct_provenance_priority:{provenance_priority}",
            f"semantic_rank_only:{semantic_rank:.4f}",
        ])
        if lexical > 0.0:
            basis.append(f"bm25_normalized:{lexical:.4f}")
        meta = conflict_meta.get(entry["id"], {})
        if meta:
            basis.append(f"conflict_set:{meta['conflict_set_id']}")
            if meta["competing_memory_ids"]:
                basis.append(
                    "conflict_competitors:"
                    + ",".join(meta["competing_memory_ids"])
                )
        direct_scores[entry["id"]] = score
        direct_basis[entry["id"]] = basis
        ranked.append((
            priority,
            score,
            entry,
            basis,
            "direct",
            facets,
            slots,
        ))

    if graph:
        seeds = [
            (score, by_id[memory_id])
            for memory_id, score in direct_scores.items()
            if score >= MIN_GRAPH_SEED_SCORE
        ]
        seeds.sort(key=lambda item: (-item[0], str(item[1]["id"])))
        existing_ranked_ids = {
            entry["id"] for _, _, entry, _, _, _, _ in ranked
        }
        for seed_score, seed in seeds[:4]:
            for neighbor in entries:
                if neighbor["id"] == seed["id"]:
                    continue
                relation = _graph_relation(seed, neighbor)
                if not relation:
                    continue
                graph_score = round(
                    max(
                        direct_scores.get(neighbor["id"], 0.0),
                        min(0.70, seed_score * 0.70),
                    ),
                    4,
                )
                neighbor_facets = _entry_facets(neighbor, action)
                neighbor_slots = _entry_slots(
                    neighbor,
                    action,
                    neighbor_facets,
                )
                relation_score, relation_basis = _target_relation(
                    neighbor, action, neighbor_facets
                )
                if (
                    not neighbor_facets
                    and not (slot_aware and neighbor_slots)
                ):
                    continue
                if (
                    relation_score <= 0
                    and slot_aware
                    and neighbor_slots
                    and relation_basis not in {
                        "incompatible_state_namespace",
                        "conflicting_target_sibling",
                    }
                ):
                    relation_score = 1
                    relation_basis = "required_state_slot_constraint"
                if relation_score <= 0:
                    continue
                basis = list(direct_basis.get(neighbor["id"], ()))
                basis.append(f"graph_one_hop:{seed['id']}:{relation}")
                basis.append(f"hard_filter_target:{relation_basis}")
                priority = (
                    relation_score * 1_000
                    + _exact_scope_score(neighbor, scope) * 100
                    + _direct_provenance_priority(neighbor) * 10
                    + len(neighbor_slots) * 3
                    + len(neighbor_facets) * 2
                    + graph_score
                )
                if neighbor["id"] in existing_ranked_ids:
                    for index, item in enumerate(ranked):
                        if item[2]["id"] == neighbor["id"]:
                            ranked[index] = (
                                max(item[0], priority),
                                max(item[1], graph_score),
                                item[2],
                                list(dict.fromkeys(item[3] + basis)),
                                "graph",
                                neighbor_facets,
                                neighbor_slots,
                            )
                            break
                else:
                    ranked.append((
                        priority,
                        graph_score,
                        neighbor,
                        basis,
                        "graph",
                        neighbor_facets,
                        neighbor_slots,
                    ))
                    existing_ranked_ids.add(neighbor["id"])

    ranked.sort(
        key=lambda item: (
            -item[0],
            -item[1],
            int(item[2].get("retrieval_rank") or 1_000_000),
            str(item[2]["id"]),
        )
    )
    next_index = 1 + max(
        [
            int(item["id"][1:])
            for item in augmented
            if str(item.get("id", "")).startswith("S")
            and str(item["id"])[1:].isdigit()
        ]
        or [0]
    )
    selected_ranked = (
        _slot_stratified_ranked(ranked, action)
        if slot_aware
        else ranked[:MAX_RETRIEVAL_CANDIDATES]
    )
    required_slots = list(action_state_slots(action))
    for priority, score, entry, basis, origin, facets, slots in selected_ranked:
        source = f"memory:{entry['id']}"
        meta = conflict_meta.get(entry["id"], {})
        if source in existing_sources:
            for item in augmented:
                if item.get("source") == source:
                    item["retrieval_rescue_candidate"] = True
                    item["candidate_retrieval_score"] = score
                    item["candidate_retrieval_priority"] = priority
                    item["candidate_retrieval_basis"] = basis
                    item["candidate_state_facets"] = sorted(facets)
                    item["candidate_state_slots"] = sorted(slots)
                    item["candidate_required_slots"] = required_slots
                    item["candidate_conflict_set_id"] = meta.get(
                        "conflict_set_id"
                    )
                    item["candidate_competing_memory_ids"] = meta.get(
                        "competing_memory_ids", []
                    )
                    break
            continue
        augmented.append({
            "id": f"S{next_index}",
            "claim": f"{entry['key']} = {entry['value']}",
            "source": source,
            "confidence": entry.get("confidence", "medium"),
            "candidate_origin": (
                "v2_graph_retrieval" if origin == "graph"
                else "v2_decision_retrieval"
            ),
            "retrieval_rescue_candidate": True,
            "candidate_retrieval_score": score,
            "candidate_retrieval_priority": priority,
            "candidate_retrieval_basis": basis,
            "candidate_state_facets": sorted(facets),
            "candidate_state_slots": sorted(slots),
            "candidate_required_slots": required_slots,
            "candidate_conflict_set_id": meta.get("conflict_set_id"),
            "candidate_competing_memory_ids": meta.get(
                "competing_memory_ids", []
            ),
            "grounder_declared": False,
        })
        existing_sources.add(source)
        next_index += 1
    return augmented


def augment_candidates(candidates, action, state, scope=None):

    augmented = [dict(item) for item in candidates]
    existing_sources = {item.get("source") for item in augmented}
    ranked = []
    for entry in memory_store.active_entries(state, scope=scope).values():
        source = f"memory:{entry['id']}"
        if source in existing_sources:
            continue
        score, basis = semantic_candidate_score(entry, action)
        if score < MIN_SEMANTIC_SCORE:
            continue
        ranked.append((
            -score,
            int(entry.get("retrieval_rank") or 1_000_000),
            str(entry["id"]),
            entry,
            basis,
        ))
    ranked.sort(key=lambda item: item[:3])

    next_index = 1 + max(
        [
            int(item["id"][1:])
            for item in augmented
            if str(item.get("id", "")).startswith("S")
            and str(item["id"])[1:].isdigit()
        ]
        or [0]
    )
    for negative_score, _, _, entry, basis in ranked[:MAX_AUGMENTED_CANDIDATES]:
        augmented.append({
            "id": f"S{next_index}",
            "claim": f"{entry['key']} = {entry['value']}",
            "source": f"memory:{entry['id']}",
            "confidence": entry.get("confidence", "medium"),
            "candidate_origin": "v2_semantic_action_retrieval",
            "candidate_retrieval_score": -negative_score,
            "candidate_retrieval_basis": basis,
            "grounder_declared": False,
        })
        next_index += 1
    return augmented


def _extract_wrapper(original):
    def wrapped(action, state, *args, **kwargs):
        candidates = original(action, state, *args, **kwargs)
        return augment_candidates(
            candidates,
            action,
            state,
            scope=kwargs.get("scope"),
        )

    return wrapped


def _retrieval_extract_wrapper(
    original,
    graph=False,
    slot_aware=False,
    conflict_aware=False,
):
    def wrapped(action, state, *args, **kwargs):
        candidates = original(action, state, *args, **kwargs)
        return retrieve_candidates(
            candidates,
            action,
            state,
            scope=kwargs.get("scope"),
            graph=graph,
            slot_aware=slot_aware,
            conflict_aware=conflict_aware,
        )

    return wrapped


def _grounding_wrapper(original):
    def wrapped(candidate, entry, action, impact):
        result = original(candidate, entry, action, impact)
        if result[0] > 0.0:
            return result
        if candidate.get("candidate_origin") != "v2_semantic_action_retrieval":
            return result
        semantic_score = float(candidate.get("candidate_retrieval_score") or 0.0)
        if semantic_score < MIN_SEMANTIC_SCORE:
            return result


        basis = candidate.get("candidate_retrieval_basis", [])
        exact_value_flow = "exact_memory_value_in_action" in basis
        return (
            min(0.75, round(semantic_score, 4)),
            "used_to_fill_argument" if exact_value_flow else "action_necessity",
            None,
            [
                f"v2_semantic_action_link:{item}"
                for item in basis
            ],
        )

    return wrapped


def _retrieval_score_wrapper(original, *, slot_aware=False):

    def wrapped(*args, **kwargs):
        scored = original(*args, **kwargs)
        original_selected = [
            item for item in scored if item.get("passed_cheap_filter")
        ]
        retrieval_candidates = [
            item
            for item in scored
            if item.get("retrieval_rescue_candidate")
            and item.get("provenance_link")
            and float(item.get("candidate_retrieval_score") or 0.0)
            >= MIN_RETRIEVAL_SCORE
        ]
        retrieval_candidates.sort(
            key=lambda item: (
                -float(item.get("candidate_retrieval_priority") or 0.0),
                -float(item.get("candidate_retrieval_score") or 0.0),
                str(item.get("memory_id") or ""),
            )
        )
        selected_ids = []
        if slot_aware:
            required_slots = list(dict.fromkeys(
                slot
                for item in retrieval_candidates
                for slot in item.get("candidate_required_slots", [])
            ))
            selectable = original_selected + [
                item
                for item in retrieval_candidates
                if item not in original_selected
            ]
            for slot in required_slots:
                match = next(
                    (
                        item
                        for item in selectable
                        if slot in item.get("candidate_state_slots", [])
                        and item.get("memory_id") not in selected_ids
                    ),
                    None,
                )
                if match is None:
                    continue
                selected_ids.append(match.get("memory_id"))
                if len(selected_ids) >= MAX_RETRIEVAL_CF_PROBES:
                    break
        for item in original_selected + retrieval_candidates:
            memory_id = item.get("memory_id")
            if memory_id and memory_id not in selected_ids:
                selected_ids.append(memory_id)
            if len(selected_ids) >= MAX_RETRIEVAL_CF_PROBES:
                break
        selected_ids = set(selected_ids)
        for item in scored:
            memory_id = item.get("memory_id")
            if not memory_id:
                continue
            if memory_id in selected_ids:
                if (
                    not item.get("passed_cheap_filter")
                    and item.get("retrieval_rescue_candidate")
                ):
                    item["passed_cheap_filter"] = True
                    item["filter_reason"] = (
                        "v2_slot_counterfactual_budget"
                        if slot_aware
                        else "v2_retrieval_counterfactual_budget"
                    )
            elif item.get("passed_cheap_filter"):
                item["passed_cheap_filter"] = False
                item["filter_reason"] = "v2_retrieval_candidate_cap"
        return scored

    return wrapped


def _retrieval_finalize_wrapper(original):

    def wrapped(scored_candidates, counterfactual_results, policy=None):
        finalized = original(
            scored_candidates,
            counterfactual_results,
            policy=policy,
        )
        for item in finalized:
            if not item.get("retrieval_rescue_candidate"):
                continue
            robust = bool(
                item.get("counterfactual_tested")
                and item.get("action_changed")
                and float(item.get("delta_cf") or 0.0) >= MIN_ROBUST_CF_DELTA
                and float(item.get("counterfactual_stability") or 0.0)
                >= MIN_ROBUST_CF_STABILITY
            )
            evidence = bool(
                item.get("provenance_link")
                and float(item.get("candidate_retrieval_score") or 0.0)
                >= MIN_RETRIEVAL_SCORE
            )
            item["robust_counterfactual"] = robust
            item["critical"] = robust and evidence
            item["critical_basis"] = (
                "v2_robust_retrieval_counterfactual"
                if item["critical"]
                else "v2_retrieval_not_critical"
            )
        return finalized

    return wrapped


def _retrieval_intervention_wrapper(original):

    def wrapped(state_claim, current_value, stage):
        interventions = original(state_claim, current_value, stage)
        fixed = [
            item
            for item in interventions
            if item.get("kind") in {"remove", "mark_uncertain"}
        ]
        replacement = next(
            (
                item for item in interventions
                if item.get("kind") == "replace"
            ),
            None,
        )
        selected = fixed[:2]
        if replacement is not None:
            selected.append(replacement)
        return selected[:MAX_RETRIEVAL_CF_INTERVENTIONS]

    return wrapped


@contextmanager
def use_variant(variant):

    method_name(variant)
    original_extract = extract_states.extract
    original_grounding = attribution.grounding_signal
    original_score = attribution.score_candidates
    original_finalize = attribution.finalize
    original_interventions = critical_detect._automatic_interventions
    try:
        if variant == "semantic_recall":
            extract_states.extract = _extract_wrapper(original_extract)
            attribution.grounding_signal = _grounding_wrapper(original_grounding)
        elif variant in {
            "retrieval",
            "retrieval_graph",
            "retrieval_slots",
            "retrieval_conflict",
            "retrieval_slots_conflict",
        }:
            slot_aware = variant in {
                "retrieval_slots",
                "retrieval_slots_conflict",
            }
            conflict_aware = variant in {
                "retrieval_conflict",
                "retrieval_slots_conflict",
            }
            extract_states.extract = _retrieval_extract_wrapper(
                original_extract,
                graph=variant == "retrieval_graph",
                slot_aware=slot_aware,
                conflict_aware=conflict_aware,
            )
            attribution.score_candidates = _retrieval_score_wrapper(
                original_score,
                slot_aware=slot_aware,
            )
            attribution.finalize = _retrieval_finalize_wrapper(original_finalize)
            critical_detect._automatic_interventions = (
                _retrieval_intervention_wrapper(original_interventions)
            )
        yield {
            "variant": variant,
            "method_name": method_name(variant),
            "method_fingerprint": method_fingerprint(variant),
        }
    finally:
        extract_states.extract = original_extract
        attribution.grounding_signal = original_grounding
        attribution.score_candidates = original_score
        attribution.finalize = original_finalize
        critical_detect._automatic_interventions = original_interventions
