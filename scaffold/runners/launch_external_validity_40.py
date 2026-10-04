from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "scaffold" / "experiments" / "paper_external_validity_40_v1"
FINAL_RUNTIME_ROOT = ROOT.parent / 'statewise'
EXPECTED_ARMS = (
    "statewise_v2_contract_corrected_typedfix",
    "corrupted",
    "rationale_approval",
    "safety_sentry",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(name: str) -> dict:
    return json.loads((PACKAGE / name).read_text(encoding="utf-8"))


def validate() -> dict:
    seal_path = PACKAGE / 'package_seal.json'
    seal = json.loads(seal_path.read_text(encoding="utf-8")) if seal_path.is_file() else None
    snapshot = _load("snapshot.json")
    matrix = _load("paired_matrix.json")
    protocol = _load("protocol_freeze.json")
    closure = _load("closure_audit.json")
    leakage = _load("leakage_audit.json")
    errors = []
    if seal is None:
        errors.append('package_seal.json is missing')
    else:
        for relative, expected in seal.get("files", {}).items():
            path = ROOT / relative
            if not path.is_file() or _sha(path) != expected:
                errors.append(f"package seal drift: {relative}")
    snapshot_sha = _sha(PACKAGE / "snapshot.json")
    if snapshot_sha != matrix.get("snapshot_sha256") or snapshot_sha != protocol.get("dataset_snapshot_sha256"):
        errors.append("snapshot fingerprint differs across frozen manifests")
    if snapshot.get("case_count") != 40 or len(snapshot.get("cases", [])) != 40:
        errors.append("snapshot is not exactly 40 cases")
    if tuple(matrix.get("arms", [])) != EXPECTED_ARMS:
        errors.append("four-arm order or identity drifted")
    if len(matrix.get("cells", [])) != 160:
        errors.append("paired matrix is not exactly 160 cells")
    by_pair = {}
    for cell in matrix.get("cells", []):
        by_pair.setdefault(cell["pairing_key"], []).append(cell)
    if len(by_pair) != 40 or any(
        tuple(item["arm"] for item in cells) != EXPECTED_ARMS
        or len({item["case_sha256"] for item in cells}) != 1
        or len({item["shared_initial_proposal_group"] for item in cells}) != 1
        for cells in by_pair.values()
    ):
        errors.append("case-level four-arm pairing contract failed")
    for entry in snapshot.get("cases", []):
        path = PACKAGE / "cases" / entry["file"]
        if not path.is_file() or _sha(path) != entry["sha256"]:
            errors.append(f"case payload drift: {entry['case_id']}")
            continue
        case = json.loads(path.read_text(encoding="utf-8"))
        policy = case.get("permission_policy", {})
        allowed = [rule.get("action") for rule in policy.get("rules", [])]
        completion = case.get("execution", {}).get("oracle", {}).get("completion_actions", [])
        if policy.get("default") != "DENY" or allowed != completion:
            errors.append(f"permission contract drift: {entry['case_id']}")
    if closure.get("status") != "VALID" or not closure.get("all_two_reset_replays_deterministic"):
        errors.append("fixture reset / closure audit is not valid")
    if leakage.get("status") != "VALID":
        errors.append("leakage audit is not valid")
    for relative, expected in protocol.get("table1_measurement_fingerprints", {}).items():
        path = FINAL_RUNTIME_ROOT / relative
        if not path.is_file() or _sha(path) != expected:
            errors.append(f"Table 1 runtime fingerprint drift: {relative}")
    for relative, expected in protocol.get("additional_prompt_permission_schema_fingerprints", {}).items():
        path = FINAL_RUNTIME_ROOT / relative
        if not path.is_file() or _sha(path) != expected:
            errors.append(f"additional protocol fingerprint drift: {relative}")

    env = os.environ.copy()
    env["STATEWISE_TYPEDFIX_FREEZE_MANIFEST"] = str(PACKAGE / "typedfix_external40_freeze.json")
    probe = f"""
import json
from pathlib import Path
from scaffold.runners import contract_corrected_typedfix_freeze as f
from scaffold.statewise.evaluation import case_schema, grading
from scaffold.statewise.experiments import pilot_conditions as p
from scaffold.statewise.runtime.lightweight_runtime import EpisodeSandbox, evaluate_oracle
arms = {EXPECTED_ARMS!r}
[p.arm_definition(a) for a in arms]
snapshot_path = Path({str(PACKAGE / 'snapshot.json')!r})
cases_root = Path({str(PACKAGE / 'cases')!r})
r = f.verify(snapshot_path, cases_root)
snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
closed = 0
graded = 0
for entry in snapshot['cases']:
    case = json.loads((cases_root / entry['file']).read_text(encoding='utf-8'))
    case_schema.assert_valid(case)
    replay = []
    for _ in range(2):
        execution = case['execution']
        with EpisodeSandbox(execution) as sandbox:
            before = sandbox.snapshot()
            action_result = sandbox.execute(execution['smoke_action'])
            after = sandbox.snapshot()
            oracle = evaluate_oracle(before, after, execution['oracle'], True, action_result, execution['smoke_action'])
        replay.append(oracle)
    if replay[0] != replay[1] or not replay[0].get('safety_pass') or not (replay[0].get('task_completed') or replay[0].get('acceptable_terminal')):
        raise RuntimeError('final-runtime closure failed: ' + case['case_id'])
    closed += 1
    synthetic = {{'final_action': execution['smoke_action'], 'residual_gate': {{'decision': 'EXECUTE'}}, 'safety_evaluation': {{'violated': False}}, 'routing_decisions': []}}
    grade = grading.grade_result(synthetic, case, case['expected']['correct']['decision'], enable_llm_judge=False)
    if not grade.get('task_completed'):
        raise RuntimeError('deterministic evaluator contract failed: ' + case['case_id'])
    graded += 1
print(json.dumps({{'freeze_valid': r['valid'], 'fingerprint': r['actual_fingerprint'], 'arms': list(arms), 'final_schema_valid': len(snapshot['cases']), 'final_runtime_closure_valid': closed, 'deterministic_evaluator_valid': graded}}))
"""
    checked = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=FINAL_RUNTIME_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if checked.returncode:
        errors.append(f"final-runtime static probe failed: {checked.stderr.strip()}")
        runtime_probe = None
    else:
        runtime_probe = json.loads(checked.stdout.strip())
        if not runtime_probe.get("freeze_valid"):
            errors.append("held-out dataset binding or frozen StateWise method is invalid")
    return {
        "ok": not errors,
        "errors": errors,
        "snapshot_sha256": snapshot_sha,
        "case_count": 40,
        "arms": list(EXPECTED_ARMS),
        "logical_episode_count": 160,
        "runtime_probe": runtime_probe,
        "api_called": False,
    }


def command(run_id: str, output_root: Path) -> list[str]:
    result = [
        sys.executable,
        "-m",
        "scaffold.runners.run_managed_pilot",
        "--snapshot",
        str(PACKAGE / "snapshot.json"),
        "--cases-root",
        str(PACKAGE / "cases"),
    ]
    for arm in EXPECTED_ARMS:
        result.extend(("--arm", arm))
    result.extend((
        "--trials", "1",
        "--run-id", run_id,
        "--output-root", str(output_root),
        "--api-profile", "api_02",
        "--max-attempts", "3",
        "--max-concurrency", "10",
        "--worker-isolation", "process",
    ))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="explicitly permit the 160 live episodes")
    parser.add_argument("--run-id", default="paper-external40-gpt56sol-20260822-r1")
    parser.add_argument("--output-root", type=Path, default=Path('runs/'))
    args = parser.parse_args()
    report = validate()
    launch = command(args.run_id, args.output_root.resolve())
    print(json.dumps({**report, "execute_requested": args.execute, "launch_command": launch}, ensure_ascii=False, indent=2))
    if not report["ok"]:
        return 2
    if not args.execute:
        return 0
    run_dir = args.output_root.resolve() / args.run_id
    if run_dir.exists():
        print(f"refusing to overwrite or resume an existing run directory: {run_dir}", file=sys.stderr)
        return 2
    env = os.environ.copy()
    env["STATEWISE_TYPEDFIX_FREEZE_MANIFEST"] = str(PACKAGE / "typedfix_external40_freeze.json")
    return subprocess.run(launch, cwd=FINAL_RUNTIME_ROOT, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
