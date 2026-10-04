from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path

from scaffold.statewise.core import action_model, attribution, extract_states
from scaffold.statewise.experiments import attribution_v2


BASE_FINGERPRINT = (
    "sha256:abee2899b4d171402d87101528cee8966bfebd023add93bf38b83ce5fd6bbedd"
)
VARIANT = "typed_action_grounding_v1"
METHOD_NAME = "StateWise-v2+TypedActionSlotGrounding"

_ACTION_ARGUMENT_SLOT_TYPES = {
    ("git", "open_pull_request"): {
        "base": "git.pr.base_branch",
        "branch": "git.pr.head_branch",
        "head": "git.pr.head_branch",
        "source": "git.pr.head_branch",
    },
    ("git", "force_push"): {"branch": "git.branch"},
    ("git", "push"): {"branch": "git.branch"},
    ("package_manager", "install"): {
        "environment": "environment.runtime",
        "package": "package.name",
    },
    ("environment", "run_python"): {
        "environment": "environment.runtime",
    },
    ("filesystem", "delete"): {"path": "filesystem.path"},
    ("filesystem", "archive"): {
        "path": "filesystem.path",
        "destination": "filesystem.path",
    },
    ("deployment", "deploy"): {
        "environment": "deployment.target",
        "region": "deployment.region",
        "service": "deployment.service",
        "version": "deployment.release",
        "release": "deployment.release",
    },
    ("database", "migrate"): {
        "database": "database.target",
        "environment": "database.target",
        "migration": "database.migration",
        "version": "database.migration",
    },
}

_ACTION_TARGET_SLOT_TYPES = {
    ("git", "open_pull_request"): "git.pr.head_branch",
    ("git", "force_push"): "git.branch",
    ("git", "push"): "git.branch",
    ("package_manager", "install"): "environment.runtime",
    ("environment", "run_python"): "environment.runtime",
    ("filesystem", "delete"): "filesystem.path",
    ("filesystem", "archive"): "filesystem.path",
    ("deployment", "deploy"): "deployment.target",
    ("database", "migrate"): "database.target",
}

_STATE_KEY_SLOT_TYPES = {
    "project_env": {"environment.runtime"},
    "python_environment": {"environment.runtime"},
    "runtime_environment": {"environment.runtime"},
    "current_branch": {"git.branch", "git.pr.head_branch"},
    "head_branch": {"git.branch", "git.pr.head_branch"},
    "source_branch": {"git.branch", "git.pr.head_branch"},
    "base_branch": {"git.branch", "git.pr.base_branch"},
    "default_branch": {"git.branch", "git.pr.base_branch"},
    "target_branch": {
        "git.branch", "git.pr.base_branch", "git.pr.head_branch",
    },
    "branch_is_protected": {"git.branch_policy"},
    "deploy_target": {"deployment.target"},
    "deployment_target": {"deployment.target"},
    "deploy_region": {"deployment.region"},
    "deployment_region": {"deployment.region"},
    "service": {"deployment.service"},
    "service_name": {"deployment.service"},
    "release_version": {"deployment.release"},
    "database_role": {"database.target"},
    "database_target": {"database.target"},
    "migration_head": {"database.migration"},
    "migration_version": {"database.migration"},
    "output_dir_status": {"filesystem.path"},
    "old_configs_usage_status": {"filesystem.path"},
    "package": {"package.name"},
    "package_name": {"package.name"},
}

_STATIC_SLOT_TYPES = {
    ("git", "open_pull_request", "target_selection"): "git.branch",
    ("git", "open_pull_request", "branch_policy"): "git.branch_policy",
    ("git", "force_push", "branch_policy"): "git.branch_policy",
    ("git", "push", "branch_policy"): "git.branch_policy",
}


def method_fingerprint():
    payload = (
        BASE_FINGERPRINT.encode("utf-8")
        + b"\n"
        + METHOD_NAME.encode("utf-8")
        + b"\n"
        + Path(__file__).read_bytes()
    )
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _scalar_values(value):
    if isinstance(value, dict):
        for nested in value.values():
            yield from _scalar_values(nested)
    elif isinstance(value, (list, tuple, set)):
        for nested in value:
            yield from _scalar_values(nested)
    elif value not in (None, ""):
        yield value


def _canonical(value):
    if isinstance(value, str):
        return value.strip().lower()
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).lower()


def _state_types(key):
    normalized = str(key or "").strip().lower()
    explicit = _STATE_KEY_SLOT_TYPES.get(normalized)
    if explicit:
        return set(explicit)
    tokens = attribution_v2._normalized_tokens(normalized)
    inferred = set()
    if tokens & {"environment", "env", "python", "runtime"}:
        inferred.add("environment.runtime")
    if "branch" in tokens:
        if tokens & {"base", "default"}:
            inferred.add("git.pr.base_branch")
        elif tokens & {"head", "source", "current"}:
            inferred.add("git.pr.head_branch")
        else:
            inferred.add("git.branch")
    if tokens & {"path", "directory", "dir"}:
        inferred.add("filesystem.path")
    return inferred


def _compatible(key, slot_type, slot_name):
    types = _state_types(key)
    if types:
        if slot_type in types:
            return True
        if slot_type in {"git.pr.base_branch", "git.pr.head_branch"}:
            return "git.branch" in types
        if slot_type == "git.branch":
            return bool(types & {
                "git.branch", "git.pr.base_branch", "git.pr.head_branch"
            })
        return False
    return bool(
        attribution_v2._normalized_tokens(key)
        & attribution_v2._normalized_tokens(slot_name)
    )


def action_argument_contract(action):
    normalized = action_model.normalize(action)
    tool_operation = (normalized.get("tool"), normalized.get("operation"))
    arguments = normalized.get("arguments") or {}
    typed = _ACTION_ARGUMENT_SLOT_TYPES.get(tool_operation, {})
    slots = {}
    for name, raw_value in arguments.items():
        values = list(_scalar_values(raw_value))
        slots[f"argument:{name}"] = {
            "name": str(name),
            "name_tokens": attribution_v2._normalized_tokens(name),
            "values": values,
            "canonical_values": {_canonical(value) for value in values},
            "value_tokens": set().union(
                *(attribution_v2._normalized_tokens(value) for value in values)
            ) if values else set(),
            "slot_type": typed.get(
                name, f"{tool_operation[0]}.{tool_operation[1]}.{name}"
            ),
        }
    targets = list(_scalar_values(normalized.get("target")))
    if targets:
        slots["argument:target"] = {
            "name": "target",
            "name_tokens": attribution_v2._normalized_tokens("target"),
            "values": targets,
            "canonical_values": {_canonical(value) for value in targets},
            "value_tokens": set().union(
                *(attribution_v2._normalized_tokens(value) for value in targets)
            ),
            "slot_type": _ACTION_TARGET_SLOT_TYPES.get(
                tool_operation,
                f"{tool_operation[0]}.{tool_operation[1]}.target",
            ),
        }
    return {
        "tool": tool_operation[0],
        "operation": tool_operation[1],
        "argument_names": set(map(str, arguments)),
        "argument_values": {
            slot["name"]: list(slot["values"])
            for name, slot in slots.items()
            if name != "argument:target"
        },
        "target_values": targets,
        "slots": slots,
    }


def matching_value_slots(entry, action):
    value = _canonical(entry.get("value"))
    value_tokens = attribution_v2._normalized_tokens(entry.get("value"))
    matches = []
    for name, slot in action_argument_contract(action)["slots"].items():
        value_matches = (
            value in slot["canonical_values"]
            or (
                value_tokens
                and value_tokens == slot["value_tokens"]
                and value_tokens
                not in ({"true"}, {"false"}, {"none"}, {"unknown"})
            )
        )
        if not value_matches:
            continue
        types = _state_types(entry.get("key"))
        if types and not _compatible(
            entry.get("key"), slot["slot_type"], slot["name"]
        ):
            continue


        matches.append((name, slot))
    return matches


def _typed_facets_wrapper(original):
    def wrapped(entry, action):
        facets = set(original(entry, action))
        if "target_binding" in facets and not matching_value_slots(
            entry, action
        ):
            facets.remove("target_binding")
        return facets
    return wrapped


def _typed_action_slots_wrapper(original):
    def wrapped(action):
        slots = original(action)
        contract = action_argument_contract(action)
        for name, slot in contract["slots"].items():
            if name in slots:

                slots[name] = set(slot["value_tokens"])
        return slots
    return wrapped


def _typed_entry_slots_wrapper(original):
    def wrapped(entry, action, facets=None):
        matched = set(original(entry, action, facets))
        contract = action_argument_contract(action)
        key_tokens = attribution_v2._normalized_tokens(entry.get("key"))
        value_tokens = attribution_v2._normalized_tokens(entry.get("value"))
        for name in list(matched):
            if name.startswith("argument:"):
                slot = contract["slots"].get(name)
                if (
                    slot is None
                    or not _compatible(
                        entry.get("key"), slot["slot_type"], slot["name"]
                    )
                    or not ((key_tokens | value_tokens) & slot["value_tokens"])
                ):
                    matched.remove(name)
                continue
            slot_type = _STATIC_SLOT_TYPES.get(
                (contract["tool"], contract["operation"], name)
            )
            if slot_type and not _compatible(
                entry.get("key"), slot_type, name
            ):
                matched.remove(name)
        return matched
    return wrapped


def _typed_binding_wrapper(original):
    def wrapped(entry, action, slots):
        strength = original(entry, action, slots)
        if strength < 4 or matching_value_slots(entry, action):
            return strength
        key_tokens = attribution_v2._normalized_tokens(entry.get("key"))
        target = attribution_v2._target_tokens(action)
        value_tokens = attribution_v2._normalized_tokens(entry.get("value"))
        if value_tokens and value_tokens <= target:
            return 4
        if target & (key_tokens - attribution_v2._GENERIC_STATE_TOKENS):
            return 3
        if any(slot.startswith("argument:") for slot in slots):
            return 3
        return 2 if slots else 1
    return wrapped


def _typed_target_relation_wrapper(original):
    def wrapped(entry, action, facets):
        relation, basis = original(entry, action, facets)
        if basis != "exact_value_in_action" or matching_value_slots(
            entry, action
        ):
            return relation, basis
        if not facets:
            return 0, "typed_exact_value_rejected"
        return 1, "typed_non_argument_constraint"
    return wrapped


def _typed_semantic_wrapper(original):
    def wrapped(entry, action):
        score, basis = original(entry, action)
        if (
            "exact_memory_value_in_action" in basis
            and not matching_value_slots(entry, action)
        ):
            score = max(0.0, round(float(score) - 0.70, 4))
            basis = [
                item for item in basis
                if item != "exact_memory_value_in_action"
            ]
            basis.append("typed_exact_value_rejected")
        elif matching_value_slots(entry, action):
            basis = list(basis) + [
                "typed_action_slot:"
                + ",".join(
                    name for name, _ in matching_value_slots(entry, action)
                )
            ]
        return score, basis
    return wrapped


def _typed_extract_wrapper(original):
    def wrapped(action, state, *args, **kwargs):
        candidates = original(action, state, *args, **kwargs)
        contract = action_argument_contract(action)
        contract_log = {
            "argument_names": sorted(contract["argument_names"]),
            "argument_values": {
                name: list(values)
                for name, values in contract["argument_values"].items()
            },
            "target_values": list(contract["target_values"]),
            "slot_types": {
                name: slot["slot_type"]
                for name, slot in contract["slots"].items()
            },
        }
        retained = []
        for candidate in candidates:
            source = str(candidate.get("source") or "")
            if candidate.get("retrieval_rescue_candidate") and source.startswith(
                "memory:"
            ):
                entry = state.get(source.split(":", 1)[1])
                if entry is not None:
                    facets = attribution_v2._entry_facets(entry, action)
                    slots = attribution_v2._entry_slots(
                        entry, action, facets
                    )
                    if not facets and not slots:
                        continue
            candidate = dict(candidate)
            candidate["candidate_action_contract"] = contract_log
            retained.append(candidate)
        return retained
    return wrapped


def _declared_slots(candidate, action):
    supported = str(candidate.get("supported_argument") or "").strip()
    contract = action_argument_contract(action)
    if supported in {"arguments", "argument"}:
        return list(contract["slots"].items())
    name = "argument:target" if supported == "target" else (
        f"argument:{supported}" if supported else ""
    )
    slot = contract["slots"].get(name)
    return [(name, slot)] if slot else []


def _typed_grounding_wrapper(original):
    def wrapped(candidate, entry, action, impact):
        matches = matching_value_slots(entry, action)
        if matches:
            name, slot = next(
                (item for item in matches if item[0] == "argument:target"),
                matches[0],
            )
            is_target = name == "argument:target"
            return (
                1.0 if is_target else 0.95,
                "used_to_fill_argument",
                slot["name"],
                [(
                    "exact_typed_target_value_match:"
                    if is_target else "exact_typed_argument_value_match:"
                ) + slot["name"]],
            )

        result = original(candidate, entry, action, impact)
        score, relation, supported, basis = result
        basis = list(basis)
        contract = action_argument_contract(action)
        value = _canonical(entry.get("value"))
        name_only = sorted(
            name for name in contract["argument_names"]
            if value == str(name).strip().lower()
        )
        declared = _declared_slots(candidate, action)
        compatible_declared = [
            item for item in declared
            if _compatible(
                entry.get("key"), item[1]["slot_type"], item[1]["name"]
            )
        ]
        incompatible = False
        if name_only:
            incompatible = True
            basis.append("argument_name_only_match:" + ",".join(name_only))
        if (
            candidate.get("grounder_declared")
            and relation == "used_to_fill_argument"
            and not compatible_declared
        ):
            incompatible = True
            basis.append(
                "typed_slot_incompatible:"
                + str(entry.get("key"))
                + ":"
                + str(supported or "unknown")
            )
        if incompatible:


            basis = [
                item for item in basis
                if item not in {
                    "exact_argument_value_match",
                    "batched_grounder_declaration",
                }
            ]
            mutation_basis = [
                item for item in basis
                if item.startswith("mutation_key_rule:")
            ]
            if not mutation_basis:
                score = 0.0
                basis.append("typed_grounding_incompatible")
        return score, relation, supported, list(dict.fromkeys(basis))
    return wrapped


def _typed_score_wrapper(original):
    def wrapped(*args, **kwargs):
        scored = original(*args, **kwargs)
        for item in scored:
            if "typed_grounding_incompatible" in item.get(
                "grounding_basis", []
            ):
                item["passed_cheap_filter"] = False
                item["filter_reason"] = "v2_typed_grounding_incompatible"
        return scored
    return wrapped


@contextmanager
def use_variant():

    originals = {
        "facets": attribution_v2._entry_facets,
        "action_slots": attribution_v2.action_state_slots,
        "entry_slots": attribution_v2._entry_slots,
        "binding": attribution_v2._action_binding_strength,
        "target_relation": attribution_v2._target_relation,
        "semantic": attribution_v2.semantic_candidate_score,
        "extract": extract_states.extract,
        "grounding": attribution.grounding_signal,
        "score": attribution.score_candidates,
    }
    attribution_v2._entry_facets = _typed_facets_wrapper(
        originals["facets"]
    )
    attribution_v2.action_state_slots = _typed_action_slots_wrapper(
        originals["action_slots"]
    )
    attribution_v2._entry_slots = _typed_entry_slots_wrapper(
        originals["entry_slots"]
    )
    attribution_v2._action_binding_strength = _typed_binding_wrapper(
        originals["binding"]
    )
    attribution_v2._target_relation = _typed_target_relation_wrapper(
        originals["target_relation"]
    )
    attribution_v2.semantic_candidate_score = _typed_semantic_wrapper(
        originals["semantic"]
    )
    extract_states.extract = _typed_extract_wrapper(originals["extract"])
    attribution.grounding_signal = _typed_grounding_wrapper(
        originals["grounding"]
    )
    attribution.score_candidates = _typed_score_wrapper(originals["score"])
    try:
        yield {
            "variant": VARIANT,
            "method_name": METHOD_NAME,
            "method_fingerprint": method_fingerprint(),
            "base_fingerprint": BASE_FINGERPRINT,
        }
    finally:
        attribution_v2._entry_facets = originals["facets"]
        attribution_v2.action_state_slots = originals["action_slots"]
        attribution_v2._entry_slots = originals["entry_slots"]
        attribution_v2._action_binding_strength = originals["binding"]
        attribution_v2._target_relation = originals["target_relation"]
        attribution_v2.semantic_candidate_score = originals["semantic"]
        extract_states.extract = originals["extract"]
        attribution.grounding_signal = originals["grounding"]
        attribution.score_candidates = originals["score"]
