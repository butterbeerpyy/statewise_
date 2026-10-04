from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


DOMAINS = {"environment", "filesystem", "git", "database", "deployment"}
REQUIRED_FLAGS = (
    "persist_memory_across_tasks",
    "reset_agent_context_between_tasks",
    "reset_workspace_between_tasks",
)


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_sequence(sequence: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    sid = sequence.get("sequence_id", "<missing>")
    domain = sequence.get("domain")
    if domain not in DOMAINS:
        errors.append(f"{sid}: invalid domain {domain!r}")
    for flag in REQUIRED_FLAGS:
        if sequence.get(flag) is not True:
            errors.append(f"{sid}: {flag} must be true")

    shared = sequence.get("shared_state") or {}
    for field in ("key", "corrupted_value", "ground_truth_value", "scope"):
        if field not in shared:
            errors.append(f"{sid}: shared_state.{field} is required")
    if shared.get("corrupted_value") == shared.get("ground_truth_value"):
        errors.append(f"{sid}: corrupted and ground-truth values must differ")

    tasks = sequence.get("tasks") or []
    if not 3 <= len(tasks) <= 5:
        errors.append(f"{sid}: requires 3-5 tasks, got {len(tasks)}")
    task_ids: set[str] = set()
    prompts: set[str] = set()
    key = shared.get("key")
    for index, task in enumerate(tasks, 1):
        tid = task.get("task_id")
        if not tid or tid in task_ids:
            errors.append(f"{sid}: missing/duplicate task_id {tid!r}")
        task_ids.add(tid)
        if task.get("task_index") != index:
            errors.append(f"{sid}/{tid}: task_index must be {index}")
        prompt = str(task.get("prompt", "")).strip()
        if not prompt or prompt in prompts:
            errors.append(f"{sid}/{tid}: missing/duplicate prompt")
        prompts.add(prompt)
        if not task.get("workspace_snapshot"):
            errors.append(f"{sid}/{tid}: workspace_snapshot is required")
        if not task.get("acceptable_outcomes"):
            errors.append(f"{sid}/{tid}: acceptable_outcomes is required")
        execution = task.get("execution") or {}
        if not execution.get("fixture") or not execution.get("oracle"):
            errors.append(f"{sid}/{tid}: executable fixture and oracle are required")
        contract = task.get("continuity_contract") or {}
        if contract.get("memory_key") != key:
            errors.append(f"{sid}/{tid}: continuity memory_key must equal shared key")
        if index == 1:
            if contract.get("role") != "repair_trigger" or not task.get("expected_memory_repair"):
                errors.append(f"{sid}/{tid}: T1 must be a repair trigger")
        else:
            if contract.get("role") != "repaired_state_reuse":
                errors.append(f"{sid}/{tid}: T2+ must reuse repaired state")
            if task.get("expected_memory_reuse") != [key] or task.get("expected_no_repeated_intervention") is not True:
                errors.append(f"{sid}/{tid}: T2+ reuse/no-repeat contract missing")
    return errors


def validate_dataset(
    sequences: Iterable[dict[str, Any]],
    *,
    expected_sequences: int | None = None,
    sequences_per_domain: int | None = None,
) -> dict[str, Any]:

    items = list(sequences)
    errors: list[str] = []
    for sequence in items:
        errors.extend(validate_sequence(sequence))
    ids = [s.get("sequence_id") for s in items]
    if len(ids) != len(set(ids)):
        errors.append("dataset: duplicate sequence_id")
    domains = Counter(s.get("domain") for s in items)

    if expected_sequences is not None and len(items) != expected_sequences:
        errors.append(
            f"dataset: expected {expected_sequences} sequences, got {len(items)}"
        )
    if not items or len(items) % len(DOMAINS):
        errors.append(
            f"dataset: sequence count must be a positive multiple of {len(DOMAINS)}, "
            f"got {len(items)}"
        )
    per_domain = sequences_per_domain
    if per_domain is None:
        per_domain = len(items) // len(DOMAINS) if items else 0
    expected = {domain: per_domain for domain in DOMAINS}
    if dict(domains) != expected:
        errors.append(f"dataset: expected domain quotas {expected}, got {dict(domains)}")
    fingerprints = [canonical_sha256({"shared_state": s.get("shared_state"), "tasks": s.get("tasks")}) for s in items]
    if len(fingerprints) != len(set(fingerprints)):
        errors.append("dataset: duplicate sequence content")
    return {
        "valid": not errors,
        "sequence_count": len(items),
        "task_count": sum(len(s.get("tasks") or []) for s in items),
        "domain_counts": dict(sorted(domains.items())),
        "errors": errors,
    }


def load_dataset(directory: Path) -> list[dict[str, Any]]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("seq_*.json"))]
