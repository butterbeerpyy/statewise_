from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "scaffold" / "cases"

SPECS = (
    ("case_env_pytest_py312", "case_canary_env_django_py313", {"P2E1": "CNE1", "pytest-dev/pytest": "django/django", "py312": "py313", "pytest": "django", "run_tests.py": "run_checks.py", "tests-success.json": "checks-success.json"}),
    ("case_env_pytest_py312", "case_canary_env_black_py311", {"P2E1": "CNE2", "pytest-dev/pytest": "psf/black", "py312": "py311", "pytest": "black", "run_tests.py": "run_format_check.py", "tests-success.json": "format-success.json"}),
    ("case_env_pytest_py312", "case_canary_env_rich_py312", {"P2E1": "CNE3", "pytest-dev/pytest": "Textualize/rich", "pytest": "rich", "run_tests.py": "run_console_check.py", "tests-success.json": "console-success.json"}),
    ("case_env_pytest_py312", "case_canary_env_mlflow_py310", {"P2E1": "CNE4", "pytest-dev/pytest": "mlflow/mlflow", "py312": "py310", "pytest": "mlflow", "run_tests.py": "run_tracking_check.py", "tests-success.json": "tracking-success.json"}),
    ("case_fs_textual_snapshots", "case_canary_fs_django_migrations", {"P2F1": "CNF1", "Textualize/textual": "django/django", "tests/__snapshots__/": "tests/migration_snapshots/", "tests/__snapshots__": "tests/migration_snapshots", "screen.svg": "schema.json", "test_screen.py": "test_migrations.py", "snapshots": "migration snapshots", "snapshot": "migration snapshot"}),
    ("case_fs_textual_snapshots", "case_canary_fs_rich_golden", {"P2F1": "CNF2", "Textualize/textual": "Textualize/rich", "tests/__snapshots__/": "tests/golden/", "tests/__snapshots__": "tests/golden", "screen.svg": "render.txt", "test_screen.py": "test_render.py", "snapshots": "golden outputs", "snapshot": "golden output"}),
    ("case_fs_textual_snapshots", "case_canary_fs_pytest_basetemp", {"P2F1": "CNF3", "Textualize/textual": "pytest-dev/pytest", "tests/__snapshots__/": "testing/baselines/", "tests/__snapshots__": "testing/baselines", "screen.svg": "collection.txt", "test_screen.py": "test_collection.py", "snapshots": "collection baselines", "snapshot": "collection baseline"}),
    ("case_git_fastapi_protected", "case_canary_git_django_release", {"P2G2": "CNG1", "tiangolo/fastapi": "django/django", "docs/rewrite": "stable/5.2.x", "FastAPI": "Django", "docs/index.md": "docs/releases/5.2.txt"}),
    ("case_git_fastapi_protected", "case_canary_git_black_docs", {"P2G2": "CNG2", "tiangolo/fastapi": "psf/black", "docs/rewrite": "docs/style-guide", "FastAPI": "Black", "docs/index.md": "docs/style_guide.md"}),
    ("case_git_fastapi_protected", "case_canary_git_rich_release", {"P2G2": "CNG3", "tiangolo/fastapi": "Textualize/rich", "docs/rewrite": "release/14.x", "FastAPI": "Rich", "docs/index.md": "docs/changes.rst"}),
)


def replace(value, substitutions):
    if isinstance(value, dict):
        return {replace(key, substitutions): replace(item, substitutions) for key, item in value.items()}
    if isinstance(value, list):
        return [replace(item, substitutions) for item in value]
    if isinstance(value, str):
        for old, new in substitutions.items():
            value = value.replace(old, new)
    return value


def main():
    for template_id, case_id, substitutions in SPECS:
        template = json.loads((CASES / f"{template_id}.json").read_text(encoding="utf-8"))
        case = replace(template, substitutions)
        case.update({
            "case_id": case_id,
            "phase": "heldout_measurement_canary_v1",
            "canary_only": True,
            "capability_score_eligible": False,
        })
        git_fixture = case.get("execution", {}).get("fixture", {}).get("git")
        if git_fixture:
            branch = git_fixture["branch"].replace("/", "__")
            base = git_fixture["base_branch"].replace("/", "__")
            case["execution"]["oracle"]["require"] = [
                f".statewise/pull_requests/{branch}--to--{base}.json"
            ]
        (CASES / f"{case_id}.json").write_text(
            json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"generated={len(SPECS)}")


if __name__ == "__main__":
    main()
