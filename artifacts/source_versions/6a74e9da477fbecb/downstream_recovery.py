from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
from pathlib import Path

from scaffold.statewise.core import main_loop
from scaffold.statewise.evaluation import safety_eval


BASE_VARIANT = "outcome_progress_guard"
BASE_FINGERPRINT = (
    "sha256:2a07600b147b9c586d1a6acc2d6e469c8ea07bd9f90481eb22597ec3452eedab"
)
VARIANT = "evidence_bound_safe_fallback"
METHOD_NAME = (
    "StateWise-v2+FacetBindingGuard+OutcomeProgressGuard"
    "+EvidenceBoundSafeFallback"
)


def method_name(variant=VARIANT):
    if variant != VARIANT:
        raise ValueError(f"unknown downstream recovery variant: {variant}")
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


def fallback_trigger(result):
    if not isinstance(result, dict):
        return None
    gate = result.get("residual_gate") or {}
    audit = result.get("outcome_progress_guard") or {}
    if gate.get("decision") != "REFUSE" or audit.get("triggered") is not True:
        return None
    if gate.get("reason") == "repeated_non_progress_mutation":
        repeated = audit.get("repeated_mismatch") or {}
        if repeated.get("type") != "non_progress_mutation":
            return None
        return {
            "trigger_kind": "repeated_non_progress_mutation",
            "goal": repeated.get("goal"),
            "effect": repeated.get("effect"),
            "source": repeated.get("source"),
            "rejected_action": copy.deepcopy(audit.get("rejected_action")),
            "recovery_action": copy.deepcopy(audit.get("recovery_action")),
        }


    recovery_gate = audit.get("recovery_gate") or {}
    if (
        gate.get("reason") != "unresolved_action_critical_state"
        or recovery_gate.get("decision") != "REFUSE"
        or recovery_gate.get("reason") != "unresolved_action_critical_state"
        or (recovery_gate.get("impact") or {}).get("is_read_only") is not False
    ):
        return None
    rejected = audit.get("rejected_action") or {}
    rejected_args = rejected.get("arguments") or {}
    return {
        "trigger_kind": "unresolved_recovery_state",
        "goal": audit.get("goal"),
        "effect": audit.get("effect"),
        "source": rejected_args.get("path") or rejected.get("target"),
        "rejected_action": copy.deepcopy(rejected),
        "recovery_action": copy.deepcopy(audit.get("recovery_action")),
        "recovery_gate": copy.deepcopy(recovery_gate),
    }


def _fallback_report(trigger):
    source = str(trigger.get("source") or "the selected source")
    if trigger.get("trigger_kind") == "unresolved_recovery_state":
        return {
            "tool": "user",
            "operation": "report",
            "arguments": {
                "message": (
                    f"No mutation was executed for {source}. A local archive "
                    "would preserve the source and create another local "
                    "artifact, so it does not directly reduce local storage. "
                    "The bounded recovery mutation was blocked because its "
                    "action-critical evidence remains unresolved; an "
                    "authoritative retention or deletion decision is needed."
                )
            },
            "target": None,
        }
    return {
        "tool": "user",
        "operation": "report",
        "arguments": {
            "message": (
                f"No mutation was executed for {source}. A local archive "
                "would preserve the source and create another local artifact, "
                "so it does not directly reduce local storage. The bounded "
                "recovery proposed the same effect again; current data was "
                "preserved and a direct retention/deletion decision is needed."
            )
        },
        "target": None,
    }


def apply_evidence_bound_fallback(result, case):

    trigger = fallback_trigger(result)
    if trigger is None:
        return result
    report = _fallback_report(trigger)
    transformed = dict(result)
    previous_gate = copy.deepcopy(result.get("residual_gate") or {})
    transformed["final_action"] = report
    transformed["residual_gate"] = {
        "decision": "EXECUTE",
        "reason": "evidence_bound_safe_fallback",
        "safe_fallback": "SAFE_REPORT_ONLY",
        "previous_gate": previous_gate,
    }
    transformed["safety_evaluation"] = safety_eval.evaluate(
        report,
        "EXECUTE",
        case.get("safety", {}),
    )
    transformed["evidence_bound_safe_fallback"] = {
        "triggered": True,
        **copy.deepcopy(trigger),
        "report_action": copy.deepcopy(report),
        "claims_task_success": False,
    }
    return transformed


def _safe_fallback_wrapper(original):
    def wrapped(*args, **kwargs):
        result = original(*args, **kwargs)
        if fallback_trigger(result) is None:
            return result
        case_path = args[0] if args else kwargs.get("case_path")
        case = main_loop.load_case(case_path)
        return apply_evidence_bound_fallback(result, case)

    return wrapped


@contextmanager
def use_variant(variant=VARIANT):
    method_name(variant)
    original_run_case = main_loop.run_case
    try:
        main_loop.run_case = _safe_fallback_wrapper(original_run_case)
        yield {
            "variant": variant,
            "method_name": method_name(variant),
            "method_fingerprint": method_fingerprint(variant),
            "base_variant": BASE_VARIANT,
            "base_fingerprint": BASE_FINGERPRINT,
            "triggers": (
                "repeated_non_progress_mutation",
                "unresolved_recovery_state",
            ),
            "terminal_action": "user.report",
        }
    finally:
        main_loop.run_case = original_run_case
