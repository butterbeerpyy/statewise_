from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT.parent / 'statewise'
POLICY_DIR = ROOT / "scaffold/answer_policy"
SNAPSHOT = (
    RUNTIME
    / "scaffold/experiments"
    / "w1_contract_corrected_v10_permission_enabled_sensitivity"
)
EXPECTED_SNAPSHOT_SHA = (
    "eefddd2ec3643136bf6bba0ecb395275e690212f55a07c028a39b8e789daed79"
)


FREEZE_MANIFEST = (
    RUNTIME
    / "scaffold/experiments"
    / "statewise_v2_contract_corrected_typedfix_v10_permission_sensitivity_freeze.json"
)
POOL = ROOT / 'paper_experiments/analysis/answer_policy_20260828/pool.json'
POLICIES = ("correct", "unavailable", "unknown", "wrong", "partial")
ARM = "statewise_v2_contract_corrected_typedfix"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _policy_env(policy: str) -> dict[str, str]:
    env = os.environ.copy()
    env["STATEWISE_ANSWER_POLICY"] = policy
    env["STATEWISE_TYPEDFIX_FREEZE_MANIFEST"] = str(FREEZE_MANIFEST)
    existing = env.get("PYTHONPATH")
    parts = [str(POLICY_DIR), str(RUNTIME)]
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _probe_policy(policy: str) -> dict:

    script = (
        "import json;"
        "from scaffold.statewise.agents import human_simulator as h;"
        "print(json.dumps({'installed': "
        "getattr(h.answer, '_answer_policy', None)}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=RUNTIME, env=_policy_env(policy),
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        return {"installed": None, "error": result.stderr.strip()[-300:]}
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return {"installed": None, "error": result.stdout.strip()[-300:]}


def validate() -> dict:
    errors: list[str] = []
    if not POOL.is_file():
        return {"ok": False, "errors": ["pool.json missing -- run prepare first"]}
    pool = json.loads(POOL.read_text(encoding="utf-8"))

    snap = SNAPSHOT / "snapshot.json"
    if not snap.is_file():
        errors.append("snapshot missing")
    elif _sha(snap) != EXPECTED_SNAPSHOT_SHA:
        errors.append("snapshot digest drift: the frozen dataset changed")


    if not FREEZE_MANIFEST.is_file():
        errors.append("freeze manifest missing: %s" % FREEZE_MANIFEST.name)
    else:
        freeze = json.loads(FREEZE_MANIFEST.read_text(encoding="utf-8"))
        base = json.loads(
            (RUNTIME / "scaffold/experiments"
             / "statewise_v2_contract_corrected_typedfix_freeze.json")
            .read_text(encoding="utf-8"))
        if freeze.get("fingerprint") != base.get("fingerprint"):
            errors.append("freeze manifest fingerprint differs from the method")
        if (freeze.get("dataset") or {}).get("snapshot_sha256") != (
                EXPECTED_SNAPSHOT_SHA):
            errors.append("freeze manifest binds a different snapshot")
        for relative, expected in freeze.get("files", {}).items():
            path = RUNTIME / relative
            if not path.is_file() or _sha(path) != expected:
                errors.append("method file drift: %s" % relative)

    cases_root = SNAPSHOT / "cases"
    for case_id in pool["case_ids"]:
        if not (cases_root / f"{case_id}.json").is_file():
            errors.append(f"pool case missing from snapshot: {case_id}")


    probes = {}
    for policy in POLICIES:
        probe = _probe_policy(policy)
        probes[policy] = probe
        if probe.get("installed") != policy:
            errors.append(
                f"policy {policy!r} did not install (got "
                f"{probe.get('installed')!r}); refusing to launch"
            )

    stock = subprocess.run(
        [sys.executable, "-c",
         "import json;from scaffold.statewise.agents import human_simulator as h;"
         "print(json.dumps({'installed': "
         "getattr(h.answer, '_answer_policy', None)}))"],
        cwd=RUNTIME, capture_output=True, text=True, check=False,
        env={**os.environ, "PYTHONPATH": str(RUNTIME)},
    )
    if stock.returncode == 0:
        if json.loads(stock.stdout.strip()).get("installed") is not None:
            errors.append("stock environment is patched; isolation is broken")

    return {
        "ok": not errors,
        "errors": errors,
        "cases": len(pool["case_ids"]),
        "policies": list(POLICIES),
        "arm": ARM,
        "logical_episode_count": len(pool["case_ids"]) * len(POLICIES),
        "policy_probes": probes,
        "snapshot_sha256": _sha(snap) if snap.is_file() else None,
        "api_called": False,
    }


def command(policy: str, run_id: str, output_root: Path,
            case_ids: list[str]) -> list[str]:
    launch = [
        sys.executable, "-m", "scaffold.runners.run_managed_pilot",
        "--snapshot", str(SNAPSHOT / "snapshot.json"),
        "--cases-root", str(SNAPSHOT / "cases"),
        "--arm", ARM,
    ]
    for case_id in case_ids:
        launch.extend(("--case", case_id))
    launch.extend((
        "--trials", "1",
        "--run-id", f"{run_id}-{policy}",
        "--output-root", str(output_root),
        "--api-profile", "api_02",
        "--max-attempts", "3",
        "--max-concurrency", "7",
        "--worker-isolation", "process",
    ))
    return launch


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--run-id", default="answerpolicy21-gpt56sol-20260828")
    parser.add_argument("--output-root", type=Path, default=Path('runs/'))
    parser.add_argument("--policy", action="append", choices=POLICIES,
                        help="restrict to specific policies")
    args = parser.parse_args()

    report = validate()
    policies = args.policy or list(POLICIES)
    pool = (json.loads(POOL.read_text(encoding="utf-8"))
            if POOL.is_file() else {"case_ids": []})
    report["launch_commands"] = {
        policy: command(policy, args.run_id, args.output_root.resolve(),
                        pool["case_ids"])
        for policy in policies
    }
    print(json.dumps({**report, "execute_requested": args.execute},
                     ensure_ascii=False, indent=2)[:4000])
    if not report["ok"]:
        return 2
    if not args.execute:
        return 0

    for policy in policies:
        run_dir = args.output_root.resolve() / f"{args.run_id}-{policy}"
        if run_dir.exists():
            print(f"skipping existing run dir: {run_dir}", file=sys.stderr)
            continue
        print(f"\n=== launching policy {policy} ===", flush=True)
        code = subprocess.run(
            report["launch_commands"][policy], cwd=RUNTIME,
            env=_policy_env(policy), check=False,
        ).returncode
        if code:
            print(f"policy {policy} exited {code}", file=sys.stderr)
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
