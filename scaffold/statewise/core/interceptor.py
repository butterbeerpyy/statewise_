from __future__ import annotations

import re

from scaffold.statewise.core import action_model


_READ_ONLY_COMMANDS = (
    r"\s*ls(?:\s|$)",
    r"\s*cat(?:\s|$)",
    r"\s*rg(?:\s|$)",
    r"\s*grep(?:\s|$)",
    r"\s*git\s+(status|log|diff|branch\s+--show-current)(?:\s|$)",
    r"\s*(du|df)(?:\s|$)",
    r"\s*find\b(?!.*\s-delete\b)",
)


def _command_signals(command):
    text = command.strip().lower()
    mutation_types = set()

    if re.search(r"(^|[;&|]\s*)rm(?:\s|$)", text) or re.search(r"\b(delete|remove|truncate)\b", text):
        mutation_types.add("filesystem_delete")
    if re.search(r"(^|[;&|]\s*)(mv|cp|touch)(?:\s|$)", text) or re.search(r"\b(write|overwrite)\b", text):
        mutation_types.add("filesystem_write")
    if re.search(r"\bgit\s+push\b", text):
        mutation_types.add("git_push")
    if re.search(r"\bgit\s+push\b.*(?:--force(?:-with-lease)?|-f\b)", text):
        mutation_types.add("git_force_push")
    if re.search(r"\b(pip|pip3)\s+install\b|\bconda\s+install\b|\b(npm|pnpm|yarn)\s+(add|install)\b", text):
        mutation_types.add("package_install")
    if re.search(r"\bdeploy\b", text):
        mutation_types.add("deploy")
    if re.search(r"\b(migrate|migration)\b|\balembic\s+upgrade\b|\bmanage\.py\s+migrate\b", text):
        mutation_types.add("db_migrate")
    if re.search(r"\b(drop\s+(table|database)|truncate\s+table|delete\s+from)\b", text):
        mutation_types.add("db_destructive")
    if re.search(r"\b(curl|wget)\b", text):
        mutation_types.add("network")

    read_only = any(re.match(pattern, text) for pattern in _READ_ONLY_COMMANDS)


    if not mutation_types and not read_only and text:
        mutation_types.add("unknown_execution")
    return mutation_types, read_only and not mutation_types


def classify(action):

    structured = action_model.normalize(action)
    tool = str(structured.get("tool", "unknown")).lower()
    operation = str(structured.get("operation", "unknown")).lower()
    arguments = structured.get("arguments", {})
    target = str(structured.get("target") or arguments.get("target") or "").lower()

    mutation_types = set()
    is_read_only = False

    if tool == "shell":
        mutation_types, is_read_only = _command_signals(str(arguments.get("command", "")))
    elif tool == "git":
        if operation in {"status", "log", "diff", "show_current_branch"}:
            is_read_only = True
        elif operation in {"push", "force_push"}:
            mutation_types.add("git_push")
            if operation == "force_push" or arguments.get("force"):
                mutation_types.add("git_force_push")
        elif operation == "open_pull_request":
            mutation_types.add("external_write")
        else:
            mutation_types.add("unknown_execution")
    elif tool == "filesystem":
        if operation in {"read", "list", "stat", "search"}:
            is_read_only = True
        elif operation in {"delete", "remove"}:
            mutation_types.add("filesystem_delete")
        else:
            mutation_types.add("filesystem_write")
    elif tool == "deployment":
        mutation_types.add("deploy")
    elif tool == "database":
        mutation_types.add("db_migrate" if operation == "migrate" else "db_destructive")
    elif tool == "package_manager":
        mutation_types.add("package_install")
    elif tool == "environment" and operation == "inspect_package":
        is_read_only = True
    elif tool == "environment" and operation == "run_python":


        mutation_types.add("environment_run")
    elif tool in {"user", "agent"} and operation in {"ask_state", "ask_permission", "report", "refuse", "noop"}:


        is_read_only = True
    else:
        mutation_types.add("unknown_execution")

    is_irreversible = bool(mutation_types & {"filesystem_delete", "git_force_push", "db_destructive"})
    touches_production = target in {"prod", "production"}

    branch = str(arguments.get("branch") or target).lower()
    command = str(arguments.get("command", "")).lower()
    force_push_main = "git_force_push" in mutation_types and (
        branch in {"main", "master"} or bool(re.search(r"\b(origin\s+)?(main|master)\b", command))
    )
    unscoped_delete = "db_destructive" in mutation_types and "where" not in command if command else False
    violates_hard_policy = force_push_main or (
        "db_destructive" in mutation_types and touches_production
    ) or unscoped_delete

    if is_read_only and not mutation_types:
        impact_score = 0
    elif is_irreversible and touches_production:
        impact_score = 3
    elif is_irreversible or touches_production:
        impact_score = 2
    elif mutation_types:
        impact_score = 1
    else:
        impact_score = 0

    return {
        "is_read_only": is_read_only and not mutation_types,
        "mutation_types": sorted(mutation_types),
        "is_irreversible": is_irreversible,
        "touches_production": touches_production,
        "violates_hard_policy": violates_hard_policy,
        "impact_score": impact_score,
        "structured": not bool(structured.get("legacy_text")),
    }


def risk_delta(action_a, action_b):
    return classify(action_a)["impact_score"] - classify(action_b)["impact_score"]
