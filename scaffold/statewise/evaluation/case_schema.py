from __future__ import annotations

from scaffold.statewise.core import action_model


PAIRED_REQUIRED = {
    "case_id",
    "task",
    "environment",
    "memory_id",
    "memory_key",
    "state_metadata",
    "ground_truth_state",
    "corrupted_state",
    "correct_state",
    "oracle_support_states",
    "safety",
    "difficulty",
    "expected",
}
MUTABLE_FIELDS = {"value", "text"}
HARD_FEATURES = {
    "D3",
    "D4",
    "multi_state",
    "decoy_memory",
    "semantic_decoy",
    "conflicting_memory",
    "cross_session_contamination",
    "observability_conflict",
    "incomplete_provenance",
    "incomplete_trace",
    "stale_plan_after_repair",
    "verification_loop",
    "non_convergence",
    "joint_state_risk",
}
CONTEXT_MEMORY_ROLES = {
    "support",
    "decoy",
    "conflict",
    "cross_session",
}
DIAGNOSTIC_TARGETS = {
    "A.critical_state_miss",
    "A.wrong_decoy_selected",
    "A.multi_state_dependency_missed",
    "A.incomplete_trace_failure",
    "B.wrong_confidence",
    "B.verification_evidence_not_incorporated",
    "B.stale_state_dominates_fresh_observation",
    "C.unnecessary_verify",
    "C.unnecessary_ask_state",
    "C.unnecessary_ask_permission",
    "C.premature_abstain",
    "D.stale_plan_after_state_repair",
    "D.repeated_read_only_loop",
    "D.non_convergence_step_limit",
    "D.correct_state_wrong_next_action",
    "E.resolved_state_action_invariant_violation",
    "F.schema",
    "F.fixture",
    "F.runtime",
    "F.oracle",
    "F.evaluator",
    "F.reset_scope_contamination",
}


def validate_case(case):
    errors = []
    if "memory_id" not in case:
        return errors

    missing = sorted(PAIRED_REQUIRED - set(case))
    errors.extend(f"missing field: {field}" for field in missing)

    for condition in ("corrupted_state", "correct_state"):
        block = case.get(condition, {})
        extra = sorted(set(block) - MUTABLE_FIELDS)
        if extra:
            errors.append(
                f"{condition} changes metadata {extra}; paired conditions may only change value/text"
            )
        if "value" not in block:
            errors.append(f"{condition}.value is required")

    correct = case.get("correct_state", {})
    truth = case.get("ground_truth_state", {})
    if correct.get("value") != truth.get("value"):
        errors.append("correct_state.value must equal ground_truth_state.value")
    if "user_authoritative" in truth and not isinstance(truth["user_authoritative"], bool):
        errors.append("ground_truth_state.user_authoritative must be boolean")
    declared_authorities = case.get("user_authoritative_keys", [])
    if not isinstance(declared_authorities, list) or not all(
        isinstance(key, str) for key in declared_authorities
    ):
        errors.append("user_authoritative_keys must be a list of strings")

    context_memories = case.get("context_memories", [])
    if not isinstance(context_memories, list):
        errors.append("context_memories must be a list")
        context_memories = []
    context_ids = set()
    for index, record in enumerate(context_memories):
        if not isinstance(record, dict):
            errors.append(f"context_memories[{index}] must be an object")
            continue
        missing_context = {
            "id", "key", "value", "confidence", "source", "scope",
            "status", "updated_at", "role",
        } - set(record)
        if missing_context:
            errors.append(
                f"context_memories[{index}] missing fields: "
                + ", ".join(sorted(missing_context))
            )
        if record.get("id") == case.get("memory_id") or record.get("id") in context_ids:
            errors.append(f"context_memories[{index}].id must be unique")
        if record.get("id"):
            context_ids.add(record["id"])
        if record.get("role") not in CONTEXT_MEMORY_ROLES:
            errors.append(f"context_memories[{index}].role is invalid")
        if record.get("role") == "cross_session" and not record.get("session_written"):
            errors.append(
                f"context_memories[{index}].session_written is required for cross_session"
            )

    hard_features = case.get("hard_features", [])
    if not isinstance(hard_features, list) or any(
        feature not in HARD_FEATURES for feature in hard_features
    ):
        errors.append("hard_features contains an unsupported feature")

    diagnostic_targets = case.get("diagnostic_targets", [])
    if diagnostic_targets and (
        not isinstance(diagnostic_targets, list)
        or any(target not in DIAGNOSTIC_TARGETS for target in diagnostic_targets)
    ):
        errors.append("diagnostic_targets contains an unsupported taxonomy label")

    truths = case.get("ground_truth_states")
    if truths is not None:
        if not isinstance(truths, list) or not truths:
            errors.append("ground_truth_states must be a non-empty list")
        elif any(
            not isinstance(item, dict) or "key" not in item or "value" not in item
            for item in truths
        ):
            errors.append("ground_truth_states entries require key and value")

    oracle = case.get("oracle_support_states", [])
    if not oracle:
        errors.append("oracle_support_states must contain at least one state")
    allowed_oracle_ids = {case.get("memory_id")} | context_ids
    for item in oracle:
        if item.get("memory_id") not in allowed_oracle_ids:
            errors.append(
                "oracle support memory_id must reference the paired or a context memory"
            )

    safety = case.get("safety", {})
    if not safety.get("invariant"):
        errors.append("safety.invariant is required")
    if not safety.get("unsafe_action"):
        errors.append("safety.unsafe_action oracle is required")
    bindings = safety.get("action_state_bindings", [])
    if not isinstance(bindings, list) or not all(
        isinstance(binding, dict)
        and isinstance(binding.get("state_key"), str)
        and (
            binding.get("argument") is None
            or isinstance(binding.get("argument"), str)
        )
        for binding in bindings
    ):
        errors.append(
            "safety.action_state_bindings must declare state_key and optional argument"
        )

    for field in ("observability", "causal_depth", "impact", "persistence", "state_cardinality"):
        if field not in case.get("difficulty", {}):
            errors.append(f"difficulty.{field} is required")

    for condition, expected in case.get("expected", {}).items():
        if not isinstance(expected, dict):
            continue
        decision = expected.get("decision", expected)
        episode = expected.get("episode")
        for field in ("acceptable_actions", "progress_actions"):
            if field in decision and not isinstance(decision[field], list):
                errors.append(f"expected.{condition}.{field} must be a list")
        if episode is not None and not isinstance(episode, dict):
            errors.append(f"expected.{condition}.episode must be an object")

    execution = case.get("execution")
    if execution is not None:
        if not isinstance(execution, dict):
            errors.append("execution must be an object")
        else:
            if execution.get("tier") != "lightweight":
                errors.append("execution.tier must be lightweight")
            smoke_action = execution.get("smoke_action")
            if not isinstance(smoke_action, dict):
                errors.append("execution.smoke_action must be a structured action")
            else:
                errors.extend(
                    f"execution.smoke_action: {error}"
                    for error in action_model.validate(smoke_action)
                )
            fixture = execution.get("fixture", {})
            oracle = execution.get("oracle", {})
            if not isinstance(fixture, dict):
                errors.append("execution.fixture must be an object")
            else:
                if not isinstance(fixture.get("files", {}), dict):
                    errors.append("execution.fixture.files must be an object")
                directories = fixture.get("directories", [])
                if not isinstance(directories, list) or not all(
                    isinstance(path, str) for path in directories
                ):
                    errors.append("execution.fixture.directories must be a list of strings")
                git_fixture = fixture.get("git")
                if git_fixture is not None and not isinstance(git_fixture, dict):
                    errors.append("execution.fixture.git must be an object")
                elif isinstance(git_fixture, dict):
                    additional_branches = git_fixture.get("additional_branches", [])
                    if not isinstance(additional_branches, list) or not all(
                        isinstance(branch, str) and branch
                        for branch in additional_branches
                    ):
                        errors.append(
                            "execution.fixture.git.additional_branches must be a list of strings"
                        )
                environments = fixture.get("python_environments", {})
                if not isinstance(environments, dict):
                    errors.append("execution.fixture.python_environments must be an object")
                scripts = fixture.get("allow_python_scripts", [])
                if not isinstance(scripts, list) or not all(isinstance(path, str) for path in scripts):
                    errors.append("execution.fixture.allow_python_scripts must be a list of strings")
                if (
                    case.get("difficulty", {}).get("observability") == "O1"
                    and case.get("memory_key") == "project_env"
                    and "CLAUDE.md" not in fixture.get("files", {})
                ):
                    errors.append(
                        "O1 project_env cases require fixture.files.CLAUDE.md "
                        "for the machine verifier"
                    )
            if not isinstance(oracle, dict):
                errors.append("execution.oracle must be an object")
            else:
                for field in ("preserve", "require", "forbid"):
                    paths = oracle.get(field, [])
                    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
                        errors.append(f"execution.oracle.{field} must be a list of strings")
                safe_actions = oracle.get("safe_terminal_actions", [])
                if not isinstance(safe_actions, list) or not all(
                    isinstance(action, dict) for action in safe_actions
                ):
                    errors.append("execution.oracle.safe_terminal_actions must be a list of actions")
                completion_actions = oracle.get("completion_actions", [])
                if not isinstance(completion_actions, list) or not all(
                    isinstance(action, dict) for action in completion_actions
                ):
                    errors.append("execution.oracle.completion_actions must be a list of actions")

    return errors


def assert_valid(case):
    errors = validate_case(case)
    if errors:
        raise ValueError(f"invalid case {case.get('case_id', '<unknown>')}: " + "; ".join(errors))
