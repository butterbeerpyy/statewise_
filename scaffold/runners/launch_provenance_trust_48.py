from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "scaffold/experiments/provenance_trust_48_v1"
FINAL_RUNTIME_ROOT = ROOT.parent / 'statewise'
BASE_CASES = (
    FINAL_RUNTIME_ROOT / "scaffold/experiments/w1_contract_corrected_v9/cases"
)
FINAL_TABLE1_MANIFEST = Path(
    'runs/permission-matched-v10-allarms20-gpt56sol-20260819-r3'
    r"\manifest.json"
)
TYPEDFIX_FREEZE = (
    FINAL_RUNTIME_ROOT
    / "scaffold/experiments/statewise_v2_contract_corrected_typedfix_freeze.json"
)
ARMS = (
    "statewise_v2_contract_corrected_typedfix",
    "memlineage_trust",
    "corrupted",
    "rationale_approval",
)


IMMUTABLE = (
    "task", "environment", "safety", "execution", "difficulty",
    "expected_behavior", "expected", "oracle_support_states",
    "memory_id", "memory_key", "correct_state", "ground_truth_state",
    "domain", "context_memories",
)
EXPECT_CONTINUE = {"HS", "HC"}
EXPECT_UNTRUSTED = {"US"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate() -> dict:
    errors: list[str] = []
    snapshot = json.loads((PACKAGE / "snapshot.json").read_text(encoding="utf-8"))
    fingerprint = json.loads(
        (PACKAGE / "snapshot_fingerprint.json").read_text(encoding="utf-8")
    )
    if _sha(PACKAGE / "snapshot.json") != fingerprint["snapshot_sha256"]:
        errors.append("snapshot digest drift")
    if snapshot["case_count"] != len(snapshot["cases"]):
        errors.append("snapshot case_count disagrees with its own case list")
    if tuple(snapshot["arms"]) != ARMS:
        errors.append("arm identity or order drifted")

    per_cell: dict[str, int] = {}
    for entry in snapshot["cases"]:
        path = PACKAGE / "cases" / entry["file"]
        if not path.is_file() or _sha(path) != entry["sha256"]:
            errors.append(f"case payload drift: {entry['case_id']}")
            continue
        case = json.loads(path.read_text(encoding="utf-8"))
        cell = case["provenance_trust_cell"]
        per_cell[cell["cell"]] = per_cell.get(cell["cell"], 0) + 1
        base_path = BASE_CASES / f"{cell['base_case_id']}.json"
        if not base_path.is_file():
            errors.append(f"missing base case: {cell['base_case_id']}")
            continue
        if _sha(base_path) != cell["base_case_sha256"]:
            errors.append(f"base case drifted since generation: {base_path.name}")
        base = json.loads(base_path.read_text(encoding="utf-8"))
        for field in IMMUTABLE:
            if json.dumps(case.get(field), sort_keys=True) != json.dumps(
                base.get(field), sort_keys=True
            ):
                errors.append(
                    f"{entry['case_id']}: immutable field changed: {field}"
                )

    if sorted(per_cell) != ["HC", "HS", "LC", "LS", "US"]:
        errors.append(f"unexpected cell set: {sorted(per_cell)}")
    if len(set(per_cell.values())) != 1:
        errors.append(f"cells are not balanced: {per_cell}")

    for relative, expected in (
        json.loads(FINAL_TABLE1_MANIFEST.read_text(encoding="utf-8"))
        ["experiment_config"]["measurement_code_fingerprints"].items()
    ):
        path = FINAL_RUNTIME_ROOT / relative
        if not path.is_file() or _sha(path) != expected:
            errors.append(f"Table 1 runtime fingerprint drift: {relative}")

    probe = _mechanism_probe()
    if probe.get("error"):
        errors.append(f"mechanism probe failed: {probe['error']}")
    else:
        for cell, stats in sorted(probe["cells"].items()):
            expect = cell in EXPECT_CONTINUE
            if expect and stats["continue"] != stats["n"]:
                errors.append(
                    f"{cell}: expected reliability-only CONTINUE on every case, "
                    f"got {stats['continue']}/{stats['n']} -- the manipulation "
                    f"is not live"
                )
            if not expect and stats["continue"]:
                errors.append(
                    f"{cell}: unexpected CONTINUE on {stats['continue']} cases"
                )
            want_untrusted = stats["n"] if cell in EXPECT_UNTRUSTED else 0
            if stats["untrusted"] != want_untrusted:
                errors.append(
                    f"{cell}: MemLineage untrusted count is "
                    f"{stats['untrusted']}, expected {want_untrusted}"
                )

    return {
        "ok": not errors,
        "errors": errors,
        "case_count": snapshot["case_count"],
        "per_cell": per_cell,
        "arms": list(ARMS),
        "logical_episode_count": snapshot["case_count"] * len(ARMS),
        "mechanism_probe": probe,
        "api_called": False,
    }


def _mechanism_probe() -> dict:

    script = f"""
import json, sys
from pathlib import Path
sys.path.insert(0, {str(FINAL_RUNTIME_ROOT)!r})
from scaffold.statewise.core import route, reliability
from scaffold.statewise.memory import memory_store
from scaffold.statewise.evaluation import case_schema
from scaffold.statewise.experiments import contract_corrected_typedfix as arm
from scaffold.statewise.experiments import memlineage_baseline as ml

package = Path({str(PACKAGE)!r})
snapshot = json.loads((package / 'snapshot.json').read_text(encoding='utf-8'))
cells = {{}}
with arm.use_variant():
    for entry in snapshot['cases']:
        case = json.loads((package / 'cases' / entry['file']).read_text(encoding='utf-8'))
        case_schema.assert_valid(case)
        cell = case['provenance_trust_cell']['cell']
        record = dict(case['state_metadata'])
        record.update({{'id': case['memory_id'], 'key': case['memory_key'],
                       'value': case['corrupted_state']['value']}})
        record.setdefault('scope', dict(memory_store.DEFAULT_SCOPE))
        record.setdefault('status', 'active')
        record.setdefault('supersedes', [])
        record.setdefault('ttl_days', None)
        record.setdefault('updated_at', 'session-1')
        record.setdefault('evidence', None)
        state = {{case['memory_id']: record}}
        for extra in case.get('context_memories') or []:
            item = dict(extra)
            for key, default in (('scope', dict(memory_store.DEFAULT_SCOPE)),
                                 ('status', 'active'), ('supersedes', []),
                                 ('ttl_days', None), ('updated_at', 'session-1'),
                                 ('evidence', None)):
                item.setdefault(key, default)
            state[item['id']] = item
        support = case['oracle_support_states'][0]
        critical = [{{'id': support['id'],
                     'source': 'memory:' + support['memory_id'],
                     'key': case['memory_key'],
                     'supported_argument': support.get('supported_argument')}}]
        scored = reliability.score(state[case['memory_id']], state,
                                   current_scope=case['environment'].get('scope'),
                                   as_of=case['environment'].get('as_of'))
        decision = route.route(critical, state,
                               {{'impact_score': 3, 'violates_hard_policy': False}},
                               case=case,
                               human_authoritative_keys=set(case.get('user_authoritative_keys') or ()))[0]
        bucket = cells.setdefault(cell, {{'n': 0, 'continue': 0, 'untrusted': 0,
                                        'reliability': []}})
        bucket['n'] += 1
        bucket['continue'] += decision['method'] == 'CONTINUE'
        bucket['untrusted'] += bool(ml._declared_untrusted(state[case['memory_id']]))
        bucket['reliability'].append(round(scored['reliability'], 3))
for bucket in cells.values():
    values = bucket.pop('reliability')
    bucket['mean_reliability'] = round(sum(values) / len(values), 3)
print(json.dumps({{'cells': cells}}))
"""
    env = os.environ.copy()
    env["STATEWISE_TYPEDFIX_FREEZE_MANIFEST"] = str(TYPEDFIX_FREEZE)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=FINAL_RUNTIME_ROOT, env=env, capture_output=True, text=True,
        check=False,
    )
    if result.returncode:
        return {"error": result.stderr.strip()[-800:]}
    return json.loads(result.stdout.strip())


def command(run_id: str, output_root: Path) -> list[str]:
    launch = [
        sys.executable, "-m", "scaffold.runners.run_managed_pilot",
        "--snapshot", str(PACKAGE / "snapshot.json"),
        "--cases-root", str(PACKAGE / "cases"),
    ]
    for arm in ARMS:
        launch.extend(("--arm", arm))
    launch.extend((
        "--trials", "1",
        "--run-id", run_id,
        "--output-root", str(output_root),
        "--api-profile", "api_02",
        "--max-attempts", "3",
        "--max-concurrency", "10",
        "--worker-isolation", "process",
    ))
    return launch


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true",
                        help="explicitly permit the live episodes")
    parser.add_argument("--run-id",
                        default="provenance-trust48-gpt56sol-20260828-r1")
    parser.add_argument("--output-root", type=Path, default=Path('runs/'))
    args = parser.parse_args()

    report = validate()
    launch = command(args.run_id, args.output_root.resolve())
    print(json.dumps({**report, "execute_requested": args.execute,
                      "launch_command": launch}, ensure_ascii=False, indent=2))
    if not report["ok"]:
        return 2
    if not args.execute:
        return 0
    run_dir = args.output_root.resolve() / args.run_id
    if run_dir.exists():
        print(f"refusing to overwrite an existing run directory: {run_dir}",
              file=sys.stderr)
        return 2
    env = os.environ.copy()
    env["STATEWISE_TYPEDFIX_FREEZE_MANIFEST"] = str(TYPEDFIX_FREEZE)
    return subprocess.run(launch, cwd=FINAL_RUNTIME_ROOT, env=env,
                          check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
