import json
import os
import re
import subprocess

from scaffold.statewise import config

FIXTURES_DIR = os.path.join(config.SCAFFOLD_ROOT, "fixtures")


def _workspace(context):
    if not context or not context.get("workspace"):
        return None
    return os.path.abspath(os.fspath(context["workspace"]))


def read_claude_md(state, context=None):

    root = _workspace(context) or config.PROJECT_ROOT
    path = os.path.join(root, "CLAUDE.md")
    if not os.path.exists(path):
        return {"status": "INSUFFICIENT"}
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    match = re.search(r"conda run -n (\w+)", text)
    if match:
        return {"status": "OBSERVED", "value": match.group(1), "evidence": "CLAUDE.md"}
    return {"status": "INSUFFICIENT"}


def conda_env_list(state, context=None):

    workspace = _workspace(context)
    if workspace:


        root = os.path.join(workspace, ".statewise", "environments")
        envs = sorted(
            name for name in os.listdir(root)
            if os.path.isdir(os.path.join(root, name))
        ) if os.path.isdir(root) else []
        return {"status": "INSUFFICIENT", "evidence": {"available_fixture_envs": envs}}
    try:
        result = subprocess.run(["conda", "env", "list", "--json"], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"status": "INSUFFICIENT"}
    if result.returncode != 0:
        return {"status": "INSUFFICIENT"}
    try:
        envs = json.loads(result.stdout).get("envs", [])
    except json.JSONDecodeError:
        return {"status": "INSUFFICIENT"}


    return {"status": "INSUFFICIENT", "evidence": {"available_envs": envs}}


def git_current_branch(state, context=None):

    root = _workspace(context) or config.PROJECT_ROOT
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=root,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"status": "INSUFFICIENT"}
    if result.returncode != 0 or not result.stdout.strip():
        return {"status": "INSUFFICIENT"}
    return {"status": "OBSERVED", "value": result.stdout.strip(), "evidence": "git branch --show-current"}


def _read_fixture(name, context=None):
    workspace = _workspace(context)
    if workspace:


        candidates = [
            os.path.join(workspace, ".statewise", "verification", name),
            os.path.join(workspace, "fixtures", name),
        ]
    else:
        candidates = [os.path.join(FIXTURES_DIR, name)]
    for path in candidates:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    return None


def read_branch_protection_fixture(state, context=None):

    fixture = _read_fixture("branch_protection.json", context=context)
    if fixture is None:
        return {"status": "INSUFFICIENT"}
    protected = fixture.get("protected_branches", [])
    current = fixture.get("current_branch")
    if current is None:
        return {"status": "INSUFFICIENT"}
    return {
        "status": "OBSERVED",
        "value": current in protected,
        "evidence": "fixtures/branch_protection.json",
    }


def read_deploy_config_fixture(state, context=None):

    fixture = _read_fixture("deploy_config.json", context=context)
    if fixture is None:
        return {"status": "INSUFFICIENT"}
    target = fixture.get("actual_target")
    if target is None:
        return {"status": "INSUFFICIENT"}
    return {"status": "OBSERVED", "value": target, "evidence": "fixtures/deploy_config.json"}


def read_db_role_fixture(state, context=None):

    fixture = _read_fixture("db_config.json", context=context)
    if fixture is None:
        return {"status": "INSUFFICIENT"}
    role = fixture.get("actual_role")
    if role is None:
        return {"status": "INSUFFICIENT"}
    return {"status": "OBSERVED", "value": role, "evidence": "fixtures/db_config.json"}


def read_gitignore_for_output_dir(state, context=None):

    return {"status": "INSUFFICIENT"}


def read_old_configs_references_fixture(state, context=None):
    fixture = _read_fixture("old_configs_references.json", context=context)
    if fixture is None or "usage_status" not in fixture:
        return {"status": "INSUFFICIENT"}
    return {
        "status": "OBSERVED",
        "value": fixture["usage_status"],
        "evidence": "fixtures/old_configs_references.json",
    }


VERIFY_TOOLS_BY_KEY = {
    "project_env": [read_claude_md, conda_env_list],
    "current_branch": [git_current_branch],
    "branch_is_protected": [read_branch_protection_fixture],
    "deploy_target": [read_deploy_config_fixture],
    "database_role": [read_db_role_fixture],
    "output_dir_status": [read_gitignore_for_output_dir],
    "old_configs_usage_status": [read_old_configs_references_fixture],
}


def try_verify(key, state, memory_id=None, context=None):

    observations = []
    for tool in VERIFY_TOOLS_BY_KEY.get(key, []):
        result = tool(state, context=context)
        if result.get("status") == "OBSERVED":
            observations.append({**result, "tool": tool.__name__})
    if not observations:
        return {"status": "INSUFFICIENT"}
    values = {json.dumps(item.get("value"), sort_keys=True) for item in observations}
    if len(values) > 1:
        return {"status": "CONFLICTING", "observations": observations}
    observed = observations[0]
    current = state.get(memory_id) if memory_id else next(
        (e for e in state.values() if e.get("status", "active") == "active" and e.get("key") == key),
        None,
    )
    status = "CONFIRMED" if current and current.get("value") == observed.get("value") else "REFUTED"
    return {**observed, "status": status}
