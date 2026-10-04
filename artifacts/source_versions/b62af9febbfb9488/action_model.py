from __future__ import annotations

import json
import re


REQUIRED_FIELDS = ("tool", "operation", "arguments")

_REQUIRED_ARGUMENTS = {
    ("filesystem", "read"): ("path",),
    ("filesystem", "list"): ("path",),
    ("filesystem", "search"): ("path", "query"),
    ("filesystem", "archive"): ("path", "destination"),
    ("filesystem", "delete"): ("path",),
    ("git", "open_pull_request"): ("branch", "base"),
    ("git", "push"): ("branch", "target"),
    ("environment", "inspect_package"): ("environment", "package"),
    ("environment", "run_python"): ("environment", "script"),
    ("package_manager", "install"): ("package",),
    ("deployment", "deploy"): ("service",),
    ("database", "migrate"): ("migration",),
}


_ARCHIVE_ALLOWED_ARGUMENTS = {
    "path",
    "destination",
    "archive_path",
    "format",
    "compression",
    "preserve_original",
    "delete_source",
    "reason",
}
_ARCHIVE_FORMATS = {"zip", "gztar", "tar.gz", "tgz"}
_ARCHIVE_COMPRESSIONS = {"best", "gzip", "gz", "9", 9}

_OPERATION_ALIASES = {
    "shell": {
        "run": "execute", "command": "execute", "exec": "execute",
    },
    "filesystem": {
        "list_directory": "list", "list_dir": "list", "read_directory": "list",
        "read_file": "read", "cat": "read", "find": "search", "search_files": "search",
        "delete_directory": "delete", "delete_file": "delete", "remove": "delete",
        "remove_directory": "delete", "compress": "archive", "archive_directory": "archive",
    },
    "git": {
        "get_status": "status", "show_status": "status", "create_pull_request": "open_pull_request",
        "pull_request": "open_pull_request", "create_pr": "open_pull_request",
        "push_branch": "push", "direct_push": "push",
    },
    "database": {
        "run_migration": "migrate", "apply_migration": "migrate", "migration": "migrate",
        "upgrade": "migrate",
    },
    "deployment": {
        "deploy_service": "deploy", "release": "deploy",


        "run_migration": "migrate",
    },
    "package_manager": {
        "install_package": "install", "add": "install",
    },
    "environment": {
        "run": "run_python", "execute_python": "run_python", "python": "run_python",
    },
    "user": {
        "ask": "ask_state", "clarify": "ask_state", "notify": "report",
    },
}

_ENV_TARGETS = {"prod", "production", "staging", "development", "dev", "configured", "current_database"}


def normalize(action):

    if isinstance(action, str):
        return {
            "tool": "shell",
            "operation": "execute",
            "arguments": {"command": action},
            "legacy_text": True,
        }
    if not isinstance(action, dict):
        raise TypeError(f"action must be a dict or string, got {type(action).__name__}")

    result = dict(action)
    result.setdefault("tool", "unknown")
    result.setdefault("operation", "unknown")
    result.setdefault("arguments", {})
    if not isinstance(result["arguments"], dict):
        raise TypeError("action.arguments must be an object")
    result["arguments"] = dict(result["arguments"])

    tool = str(result["tool"]).lower()
    operation = str(result["operation"]).lower()


    if operation.startswith(f"{tool}."):
        operation = operation.split(".", 1)[1]
    operation = _OPERATION_ALIASES.get(tool, {}).get(operation, operation)
    if tool == "deployment" and operation == "migrate":
        tool = "database"
    if tool == "git" and operation == "push" and result["arguments"].get("force"):
        operation = "force_push"

    result["tool"] = tool
    result["operation"] = operation
    if tool == "filesystem":
        path = result["arguments"].get("path")
        if isinstance(path, str) and path not in {"", ".", "/"}:
            result["arguments"]["path"] = path.replace("\\", "/").rstrip("/")
    if tool == "filesystem" and operation == "search":
        if "query" not in result["arguments"] and "pattern" in result["arguments"]:
            result["arguments"]["query"] = result["arguments"]["pattern"]
    if tool == "filesystem" and operation == "archive":
        if "destination" not in result["arguments"] and "archive_path" in result["arguments"]:
            result["arguments"]["destination"] = result["arguments"]["archive_path"]
    if tool == "git" and operation == "open_pull_request":
        if "branch" not in result["arguments"] and isinstance(result["arguments"].get("head"), str):
            result["arguments"]["branch"] = result["arguments"]["head"]
    if tool == "package_manager" and operation == "install":
        packages = result["arguments"].get("packages")
        if "package" not in result["arguments"] and isinstance(packages, list) and len(packages) == 1:
            result["arguments"]["package"] = packages[0]


    argument_target = result["arguments"].get("target")
    current_target = result.get("target")
    if tool in {"deployment", "database"}:
        role = result["arguments"].get("role")
        explicit_is_concrete = isinstance(current_target, str) and current_target.lower() in {
            "prod", "production", "staging", "development", "dev"
        }
        if explicit_is_concrete:
            pass
        elif isinstance(argument_target, str) and argument_target.lower() in _ENV_TARGETS:
            current_target = argument_target
        elif isinstance(role, str) and role.lower() in _ENV_TARGETS:
            current_target = role
    elif tool in {"package_manager", "environment"}:
        argument_environment = result["arguments"].get("environment")


        if (
            isinstance(argument_environment, str)
            and current_target in (None, "", "configured", "current")
        ):
            current_target = argument_environment
    elif tool == "git" and not current_target:
        branch = result["arguments"].get("branch")
        if isinstance(branch, str):
            current_target = branch
    if current_target is not None:
        result["target"] = current_target
    return result


def contextualize(action, state):

    result = normalize(action)
    target = result.get("target")
    if target not in (None, "", "current", "current_database"):
        return result

    active = [entry for entry in state.values() if entry.get("status", "active") == "active"]
    by_key = {entry.get("key"): entry.get("value") for entry in active}
    tool, operation = result["tool"], result["operation"]
    command = str(result.get("arguments", {}).get("command", "")).lower()

    key = None
    if tool == "deployment" and operation == "deploy":
        key = "deploy_target"
    elif tool == "database" and operation == "migrate":
        key = "database_role"
    elif tool == "package_manager" and operation == "install":
        key = "project_env"
    elif tool == "shell" and re.search(r"\b(alembic\s+upgrade|manage\.py\s+migrate|flyway|liquibase)\b", command):
        key = "database_role"

    if key and by_key.get(key) is not None:
        result["target"] = by_key[key]
        result["target_source"] = f"memory_key:{key}"
    return result


def validate(action):

    if not isinstance(action, dict):
        return ["action is not a structured object"]
    errors = [f"missing action.{field}" for field in REQUIRED_FIELDS if field not in action]
    if "arguments" in action and not isinstance(action["arguments"], dict):
        errors.append("action.arguments is not an object")
        return errors
    try:
        normalized = normalize(action)
    except (TypeError, ValueError) as exc:
        errors.append(str(exc))
        return errors
    arguments = normalized.get("arguments", {})
    for field in _REQUIRED_ARGUMENTS.get(
        (normalized.get("tool"), normalized.get("operation")), ()
    ):
        if arguments.get(field) in (None, ""):
            errors.append(
                f"{normalized.get('tool')}.{normalized.get('operation')} "
                f"requires arguments.{field}"
            )
    if (
        normalized.get("tool") == "filesystem"
        and normalized.get("operation") == "archive"
    ):
        errors.extend(archive_contract_errors(arguments))
    if normalized.get("tool") in {"environment", "package_manager"}:
        explicit_target = normalized.get("target")
        argument_environment = normalized.get("arguments", {}).get("environment")
        if (
            isinstance(explicit_target, str)
            and isinstance(argument_environment, str)
            and explicit_target != argument_environment
        ):
            errors.append(
                "conflicting action.target and action.arguments.environment"
            )
    if (
        normalized.get("tool") == "git"
        and normalized.get("operation") == "open_pull_request"
        and arguments.get("branch") == arguments.get("base")
        and arguments.get("branch") not in (None, "")
    ):
        errors.append("git.open_pull_request branch and base must differ")
    return errors


def archive_contract_errors(arguments):

    if not isinstance(arguments, dict):
        return ["filesystem.archive arguments must be an object"]
    errors = []
    for field in sorted(set(arguments) - _ARCHIVE_ALLOWED_ARGUMENTS):
        errors.append(
            f"filesystem.archive does not support arguments.{field}"
        )
    destination = arguments.get("destination")
    archive_path = arguments.get("archive_path")
    if (
        destination not in (None, "")
        and archive_path not in (None, "")
        and destination != archive_path
    ):
        errors.append(
            "filesystem.archive has conflicting arguments.destination "
            "and arguments.archive_path"
        )
    if arguments.get("delete_source") not in (None, False):
        errors.append(
            "filesystem.archive is source-preserving; use a separate "
            "filesystem.delete action instead of arguments.delete_source"
        )
    if arguments.get("preserve_original") not in (None, True):
        errors.append(
            "filesystem.archive requires arguments.preserve_original=true"
        )
    archive_format = arguments.get("format")
    normalized_format = (
        archive_format.casefold()
        if isinstance(archive_format, str)
        else archive_format
    )
    if (
        archive_format not in (None, "")
        and normalized_format not in _ARCHIVE_FORMATS
    ):
        errors.append(
            "filesystem.archive supports only zip or gzip-tar "
            "(format=zip|gztar|tar.gz|tgz)"
        )
    compression = arguments.get("compression")
    normalized_compression = (
        compression.casefold() if isinstance(compression, str) else compression
    )
    if (
        compression not in (None, "")
        and normalized_compression not in _ARCHIVE_COMPRESSIONS
    ):
        errors.append(
            "filesystem.archive supports only best/gzip compression"
        )
    destination_format = None
    if isinstance(destination, str):
        lowered_destination = destination.casefold()
        if lowered_destination.endswith(".zip"):
            destination_format = "zip"
        elif lowered_destination.endswith((".tar.gz", ".tgz")):
            destination_format = "gztar"
        else:
            errors.append(
                "filesystem.archive destination must end with "
                ".zip, .tar.gz, or .tgz"
            )
    requested_format = (
        "gztar"
        if normalized_format in {"gztar", "tar.gz", "tgz"}
        else normalized_format
    )
    if (
        requested_format not in (None, "")
        and destination_format is not None
        and requested_format != destination_format
    ):
        errors.append(
            "filesystem.archive format conflicts with destination extension"
        )
    return errors


def canonical(action):

    if action is None:
        return "null"
    normalized = normalize(action)
    comparable = {
        "tool": normalized.get("tool"),
        "operation": normalized.get("operation"),
        "arguments": normalized.get("arguments", {}),
        "target": normalized.get("target"),
        "working_directory": normalized.get("working_directory"),
    }
    return json.dumps(comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def equivalent(left, right):
    return canonical(left) == canonical(right)


def display(action):

    normalized = normalize(action)
    if normalized["tool"] == "shell" and "command" in normalized["arguments"]:
        return normalized["arguments"]["command"]
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)
