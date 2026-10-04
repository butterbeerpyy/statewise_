from __future__ import annotations

from typing import Any, Mapping

from scaffold.statewise.core import interceptor


REFERENCE = "MemLineage: Lineage-Guided Enforcement for LLM Agent Memory (arXiv:2605.14421)"
IMPLEMENTATION_FIDELITY = "clean_room_style_gate_without_cryptographic_signatures"

_TRUSTED_SOURCES = {
    "agent_inference",
    "agent_summary",
    "historical_interaction",
    "host_state",
    "human_simulator_confirmed",
    "user_confirmed",
    "user_preference",
}
_TRUSTED_PREFIXES = ("tool_verified:", "audited_tool:", "internal:", "user:", "host:")
_UNTRUSTED_PREFIXES = (
    "external:",
    "web:",
    "unverified:",
    "upstream_agent:",
    "unaudited_tool:",
    "retrieved_document:",
)


def fidelity_manifest() -> dict[str, Any]:
    return {
        "reference": REFERENCE,
        "implementation_fidelity": IMPLEMENTATION_FIDELITY,
        "cryptographic_origin_binding": False,
        "lineage_propagation": "max_untrusted_ancestry",
        "dispatch_policy": "block_sensitive_action_on_untrusted_justification",
        "does_not_check": ["memory_factual_correctness", "freshness", "state_verification"],
    }


def _declared_untrusted(entry: Mapping[str, Any]) -> bool:
    tier = str(entry.get("provenance_tier") or entry.get("trust_tier") or "").lower()
    if tier:
        return tier in {"external", "untrusted", "unverified"}
    source = str(entry.get("source") or "").lower()
    if source in _TRUSTED_SOURCES or source.startswith(_TRUSTED_PREFIXES):
        return False
    if source.startswith(_UNTRUSTED_PREFIXES):
        return True

    return True


def _parents(entry: Mapping[str, Any]) -> list[str]:
    raw = entry.get("derived_from", entry.get("lineage_parents", []))
    if isinstance(raw, str):
        return [raw]
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _is_untrusted_path(
    entry_id: str,
    state: Mapping[str, Mapping[str, Any]],
    visiting: set[str] | None = None,
) -> bool:
    visiting = set(visiting or ())
    if entry_id in visiting:
        return True
    entry = state.get(entry_id)
    if not isinstance(entry, Mapping):
        return True
    if _declared_untrusted(entry):
        return True
    visiting.add(entry_id)
    return any(_is_untrusted_path(parent, state, visiting) for parent in _parents(entry))


def gate_action(
    action: Mapping[str, Any],
    state: Mapping[str, Mapping[str, Any]],
    justification_memory_ids: list[str],
) -> dict[str, Any]:
    impact = interceptor.classify(action)
    if impact.get("is_read_only"):
        return {
            "decision": "EXECUTE",
            "reason": "read_only_action",
            "untrusted_justification_ids": [],
            "impact": impact,
        }
    untrusted = sorted({
        entry_id
        for entry_id in justification_memory_ids
        if _is_untrusted_path(entry_id, state)
    })
    return {
        "decision": "REFUSE" if untrusted else "EXECUTE",
        "reason": (
            "untrusted_lineage_in_active_justification"
            if untrusted else "trusted_lineage_does_not_assess_correctness"
        ),
        "untrusted_justification_ids": untrusted,
        "impact": impact,
        "implementation_fidelity": IMPLEMENTATION_FIDELITY,
    }
