from __future__ import annotations

import pytest

from scaffold.statewise.runtime.lightweight_runtime import EpisodeSandbox, RuntimePolicyError


def test_database_migration_is_local_deterministic_marker():
    execution = {
        "fixture": {
            "database_runtime": {
                "allow_migrate": True,
                "allowed_migrations": ["m42"],
                "targets": {"staging": {"role": "primary"}},
            }
        }
    }
    action = {
        "tool": "database",
        "operation": "migrate",
        "arguments": {"migration": "m42", "target": "staging"},
        "target": "staging",
    }
    with EpisodeSandbox(execution) as sandbox:
        result = sandbox.execute(action)
        first = sandbox.resolve(result["record"]).read_bytes()
        sandbox.execute(action)
        second = sandbox.resolve(result["record"]).read_bytes()
    assert first == second
    assert result["record"] == ".statewise/database/migrations/staging/m42.json"


def test_deployment_rejects_undeclared_target():
    execution = {
        "fixture": {
            "deployment_runtime": {
                "allow_deploy": True,
                "allowed_services": ["api"],
                "targets": {"staging": {"cluster": "staging-a"}},
            }
        }
    }
    action = {
        "tool": "deployment",
        "operation": "deploy",
        "arguments": {"service": "api", "target": "production"},
        "target": "production",
    }
    with EpisodeSandbox(execution) as sandbox:
        with pytest.raises(RuntimePolicyError, match="undeclared deployment target"):
            sandbox.execute(action)


def test_empty_fixture_environment_is_materialized_for_python_run():
    execution = {
        "fixture": {
            "files": {"task.py": "print('ok')\n"},
            "python_environments": {"nightly": {"packages": []}},
            "allow_python_scripts": ["task.py"],
        }
    }
    action = {
        "tool": "environment",
        "operation": "run_python",
        "arguments": {"environment": "nightly", "script": "task.py"},
        "target": "nightly",
    }
    with EpisodeSandbox(execution) as sandbox:
        result = sandbox.execute(action)
    assert result["ok"] is True


def test_git_pull_request_supports_declared_remote_base_and_logical_option():
    execution = {
        "fixture": {
            "git": {
                "init": True,
                "bare_remote": True,
                "branch": "feature/rq5",
                "base_branch": "main",
                "additional_branches": ["release/2.x"],
                "pull_request_options": {"strategy": ["squash"]},
            }
        }
    }
    action = {
        "tool": "git",
        "operation": "open_pull_request",
        "arguments": {
            "branch": "feature/rq5",
            "base": "release/2.x",
            "strategy": "squash",
        },
        "target": "feature/rq5",
    }
    with EpisodeSandbox(execution) as sandbox:
        result = sandbox.execute(action)
        assert sandbox.resolve(result["record"]).is_file()
    assert result["record"].endswith("--strategy-squash.json")
