from __future__ import annotations

import json
from typing import Any, Mapping


class StructuredMutationPolicyError(RuntimeError):
    pass


def _safe_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or not all(
        character.isalnum() or character in "._-" for character in value
    ):
        raise StructuredMutationPolicyError(f"invalid {field}: {value!r}")
    return value


def _target(action: Mapping[str, Any]) -> str:
    arguments = action.get("arguments") or {}
    return _safe_identifier(
        action.get("target") or arguments.get("target"), "action target"
    )


def _contract(fixture: Mapping[str, Any], tool: str) -> Mapping[str, Any]:
    contract = fixture.get(f"{tool}_runtime")
    if not isinstance(contract, Mapping):
        raise StructuredMutationPolicyError(
            f"{tool} runtime is not enabled by this case fixture"
        )
    targets = contract.get("targets")
    if not isinstance(targets, Mapping) or not targets:
        raise StructuredMutationPolicyError(
            f"{tool}_runtime.targets must declare at least one target"
        )
    return contract


def _write_marker(sandbox: Any, relative: str, payload: Mapping[str, Any]) -> str:
    marker = sandbox.resolve(relative, must_exist=False)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return marker.relative_to(sandbox.workspace).as_posix()


def execute(sandbox: Any, action: Mapping[str, Any]) -> dict[str, Any]:

    tool = action.get("tool")
    operation = action.get("operation")
    if tool not in {"database", "deployment"}:
        raise StructuredMutationPolicyError(f"unsupported structured tool: {tool!r}")

    fixture = sandbox.spec.get("fixture") or {}
    contract = _contract(fixture, tool)
    arguments = action.get("arguments") or {}
    target = _target(action)
    targets = contract["targets"]
    if target not in targets:
        raise StructuredMutationPolicyError(
            f"undeclared {tool} target: {target!r}"
        )

    if tool == "database" and operation == "migrate":
        if contract.get("allow_migrate") is not True:
            raise StructuredMutationPolicyError("database migration is not enabled")
        migration = _safe_identifier(arguments.get("migration"), "migration")
        allowed = contract.get("allowed_migrations") or []
        if allowed and migration not in allowed:
            raise StructuredMutationPolicyError(
                f"migration is not allowlisted: {migration!r}"
            )
        relative = f".statewise/database/migrations/{target}/{migration}.json"
        record = _write_marker(
            sandbox,
            relative,
            {
                "contract_version": 1,
                "migration": migration,
                "operation": "migrate",
                "target": target,
                "target_state": targets[target],
                "tool": "database",
            },
        )
        return {
            "ok": True,
            "tool": tool,
            "operation": operation,
            "target": target,
            "migration": migration,
            "record": record,
        }

    if tool == "deployment" and operation == "deploy":
        if contract.get("allow_deploy") is not True:
            raise StructuredMutationPolicyError("deployment is not enabled")
        service = _safe_identifier(arguments.get("service"), "service")
        allowed = contract.get("allowed_services") or []
        if allowed and service not in allowed:
            raise StructuredMutationPolicyError(
                f"service is not allowlisted: {service!r}"
            )
        relative = f".statewise/deployments/{target}/{service}.json"
        record = _write_marker(
            sandbox,
            relative,
            {
                "contract_version": 1,
                "operation": "deploy",
                "service": service,
                "target": target,
                "target_state": targets[target],
                "tool": "deployment",
            },
        )
        return {
            "ok": True,
            "tool": tool,
            "operation": operation,
            "target": target,
            "service": service,
            "record": record,
        }

    raise StructuredMutationPolicyError(
        f"unsupported structured action {tool}.{operation}"
    )
