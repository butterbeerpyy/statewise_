from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
from pathlib import Path

from scaffold.statewise.core import action_model, main_loop
from scaffold.statewise.evaluation import safety_eval


BASE_VARIANT = "facet_binding_guard"
BASE_FINGERPRINT = (
    "sha256:281e42e2bd78a0f6fb6d48aa9c1b73a0f34ced089752b4619d2185e804e46649"
)
VARIANT = "outcome_progress_guard"
METHOD_NAME = "StateWise-v2+FacetBindingGuard+OutcomeProgressGuard"

_STORAGE_REDUCTION_MARKERS = (
    "free space",
    "disk space",
    "storage pressure",
    "reduce storage",
    "cleanup",
    "clean up",
    "delete",
    "remove",
    "占用",
    "释放空间",
    "腾出空间",
    "清理",
    "删掉",
    "删除",
)
_EXPLICIT_ARCHIVE_MARKERS = (
    "archive",
    "compress",
    "backup",
    "preserve",
    "归档",
    "压缩",
    "备份",
    "打包",
    "留证",
)


def method_name(variant=VARIANT):
    if variant != VARIANT:
        raise ValueError(f"unknown downstream progress variant: {variant}")
    return METHOD_NAME


def method_fingerprint(variant=VARIANT):
    payload = (
        BASE_FINGERPRINT.encode("utf-8")
        + b"\n"
        + method_name(variant).encode("utf-8")
        + b"\n"
        + Path(__file__).read_bytes()
    )
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _contains_any(text, markers):
    lowered = str(text or "").casefold()
    return any(marker.casefold() in lowered for marker in markers)


def task_goal(task):

    if _contains_any(task, _EXPLICIT_ARCHIVE_MARKERS):
        return "explicit_archive_or_preservation"
    if _contains_any(task, _STORAGE_REDUCTION_MARKERS):
        return "local_storage_reduction"
    return "other"


def goal_effect_mismatch(task, result):

    if not isinstance(result, dict):
        return None
    gate = result.get("residual_gate") or {}
    if gate.get("decision") != "EXECUTE":
        return None
    action = result.get("final_action")
    if not isinstance(action, dict):
        return None
    try:
        normalized = action_model.normalize(action)
    except (TypeError, ValueError):
        return None
    if (
        normalized.get("tool") != "filesystem"
        or normalized.get("operation") != "archive"
        or task_goal(task) != "local_storage_reduction"
    ):
        return None
    arguments = normalized.get("arguments") or {}
    return {
        "type": "non_progress_mutation",
        "goal": "local_storage_reduction",
        "effect": "archive_preserves_source_and_creates_local_destination",
        "reason": "local_archive_cannot_directly_reduce_local_storage",
        "action": copy.deepcopy(normalized),
        "source": arguments.get("path"),
        "destination": arguments.get("destination"),
    }


def _merge_replan(initial, recovered, mismatch, repeated):
    merged = dict(recovered)
    for field in (
        "initial_action",
        "initial_rationale",
        "planner_context_memory_ids",
        "initial_impact",
        "support_states",
        "annotated_states",
        "attribution_metrics",
        "critical_states",
    ):
        if field in initial:
            merged[field] = copy.deepcopy(initial[field])
    for field in (
        "inspection_rounds",
        "routing_decisions",
        "questions_asked",
        "human_interactions",
    ):
        merged[field] = (
            copy.deepcopy(initial.get(field) or [])
            + copy.deepcopy(recovered.get(field) or [])
        )
    merged["replan_count"] = (
        int(initial.get("replan_count") or 0)
        + 1
        + int(recovered.get("replan_count") or 0)
    )
    if repeated is not None:
        merged["residual_gate"] = {
            "decision": "REFUSE",
            "reason": "repeated_non_progress_mutation",
            "safe_fallback": "ABSTAIN",
            "progress_gate": copy.deepcopy(repeated),
        }
        case = merged.pop("_progress_case", None)
        if case is not None:
            merged["safety_evaluation"] = safety_eval.evaluate(
                merged.get("final_action"),
                "REFUSE",
                case.get("safety", {}),
            )
    merged["outcome_progress_guard"] = {
        "triggered": True,
        "rejected_action": copy.deepcopy(mismatch["action"]),
        "goal": mismatch["goal"],
        "effect": mismatch["effect"],
        "reason": mismatch["reason"],
        "recovery_action": copy.deepcopy(recovered.get("final_action")),
        "recovery_gate": copy.deepcopy(merged.get("residual_gate") or {}),
        "repeated_mismatch": copy.deepcopy(repeated),
    }
    return merged


def _outcome_progress_wrapper(original):


    def wrapped(*args, **kwargs):
        initial = original(*args, **kwargs)
        case_path = args[0] if args else kwargs.get("case_path")
        case = main_loop.load_case(case_path)
        mismatch = goal_effect_mismatch(case.get("task", ""), initial)
        if mismatch is None:
            return initial

        observation = {
            "ok": False,
            "progress_gate": {
                key: copy.deepcopy(value)
                for key, value in mismatch.items()
                if key != "action"
            },
            "rejected_action": copy.deepcopy(mismatch["action"]),
            "instruction": (
                "The rejected action was not executed. Select a direct safe "
                "task action consistent with resolved state, or user.report "
                "when no safe progress action exists. Do not create another "
                "local archive merely to satisfy a storage-reduction goal."
            ),
        }
        recovery_kwargs = dict(kwargs)
        recovery_kwargs.pop("initial_proposal", None)
        recovery_kwargs["initial_state"] = copy.deepcopy(
            initial.get("final_memory") or {}
        )
        recovery_kwargs["initial_observation"] = observation
        prior_trajectory = list(recovery_kwargs.get("trajectory") or [])
        prior_trajectory.append(
            {
                "type": "PLAN_REJECTED",
                "action": copy.deepcopy(mismatch["action"]),
                "progress_gate": copy.deepcopy(observation["progress_gate"]),
            }
        )
        recovery_kwargs["trajectory"] = prior_trajectory
        recovery_kwargs["initial_stage_suffix"] = "outcome_progress_replan"
        recovered = original(*args, **recovery_kwargs)
        repeated = goal_effect_mismatch(case.get("task", ""), recovered)


        if repeated is not None:
            recovered = {**recovered, "_progress_case": case}
        return _merge_replan(initial, recovered, mismatch, repeated)

    return wrapped


@contextmanager
def use_variant(variant=VARIANT):

    method_name(variant)
    original_run_case = main_loop.run_case
    try:
        main_loop.run_case = _outcome_progress_wrapper(original_run_case)
        yield {
            "variant": variant,
            "method_name": method_name(variant),
            "method_fingerprint": method_fingerprint(variant),
            "base_variant": BASE_VARIANT,
            "base_fingerprint": BASE_FINGERPRINT,
            "max_recovery_replans": 1,
            "effect_rules": [
                "local_archive_preserves_source_and_adds_destination"
            ],
        }
    finally:
        main_loop.run_case = original_run_case
