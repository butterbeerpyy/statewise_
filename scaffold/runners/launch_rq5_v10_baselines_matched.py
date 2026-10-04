from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
METHOD_ROOT = ROOT.parent / 'statewise'
RUNNER = METHOD_ROOT / "scaffold/runners/run_rq5_longitudinal_real.py"
DATASET = ROOT / "scaffold/experiments/rq5_longitudinal_40_v2"
OUTPUT = Path('runs/')
DATASET_SHA256 = "a871a91427dd4a5bead0115be695bb74df28a660b25990103cdece681b4b7a62"
DOMAINS = {"env": "environment", "git": "git", "db": "database", "dep": "deployment"}
ARMS = {"mem": "memlineage_trust", "saf": "safety_sentry", "ask": "ask_or_assume"}
EXPECTED_CODE_HASHES = {
    "scaffold/runners/run_rq5_longitudinal_real.py": "43d82c8b558d521ce04386c1b1991a173ecc511d941cd087387e1044d369ff7a",
    "scaffold/statewise/evaluation/longitudinal_runtime.py": "22155e13e81af07f558e0901d051f76aed745fe92c4520a4d667e39747e1d811",
    "scaffold/statewise/evaluation/longitudinal_schema.py": "efc90579f490e901ccef46a2c0fb1228f19a67379c6c7350f7dacae2fdd72317",
    "scaffold/statewise/experiments/pilot_conditions.py": "ba12ee8679e7f507e3a117b7f8ff6351bd43e16f9945969542e8e1a79955750a",
    "scaffold/statewise/runtime/lightweight_runtime.py": "844f36ee193f05cb1c12b46a34de55855a58f6b053b9a1171d601d1c314ae4ec",
    "scaffold/statewise/runtime/structured_mutation_runtime.py": "00b14b89334287ee06c704a79e848aac94780213a91f1528b88e07b17f099540",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_inputs() -> None:
    mismatches = {
        relative: {"expected": expected, "actual": sha256(METHOD_ROOT / relative)}
        for relative, expected in EXPECTED_CODE_HASHES.items()
        if not (METHOD_ROOT / relative).is_file()
        or sha256(METHOD_ROOT / relative) != expected
    }
    if mismatches:
        raise RuntimeError(f"method worktree hash mismatch: {mismatches}")
    manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("composite_sha256") != DATASET_SHA256:
        raise RuntimeError("RQ5 dataset composite SHA changed")


def expected_sequences(domain: str) -> list[str]:
    return [f"seq_{domain}_{index:03d}" for index in range(1, 9)]


def command(run_id: str, arm: str, sequences: list[str]) -> list[str]:
    args = [
        sys.executable,
        str(RUNNER),
        str(DATASET),
        "--run-id", run_id,
        "--output-root", str(OUTPUT),
        "--arm", arm,
        "--api-profile", "rightapi_gpt56sol",
        "--max-concurrency", "1",
        "--max-attempts", "3",
        "--execute",
    ]
    for sequence_id in sequences:
        args.extend(("--sequence-id", sequence_id))
    return args


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", action="append", choices=sorted(DOMAINS))
    parser.add_argument("--validation-timeout", type=int, default=120)
    args = parser.parse_args()
    validate_inputs()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    processes = []
    selected_domains = {
        code: domain for code, domain in DOMAINS.items()
        if not args.domain or code in args.domain
    }
    for domain_code, domain in selected_domains.items():
        sequences = expected_sequences(domain)
        for arm_code, arm in ARMS.items():
            run_id = f"r5v10-{domain_code}-{arm_code}-b3"
            stdout = (OUTPUT / f"{run_id}.stdout.log").open("w", encoding="utf-8")
            stderr = (OUTPUT / f"{run_id}.stderr.log").open("w", encoding="utf-8")
            process = subprocess.Popen(
                command(run_id, arm, sequences),
                cwd=METHOD_ROOT,
                stdout=stdout,
                stderr=stderr,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            stdout.close()
            stderr.close()
            processes.append((run_id, domain, sequences, process))

    deadline = time.monotonic() + args.validation_timeout
    pending = {run_id: item for run_id, *item in processes}
    while pending and time.monotonic() < deadline:
        for run_id, item in list(pending.items()):
            domain, sequences, process = item
            manifest_path = OUTPUT / run_id / "manifest.json"
            if not manifest_path.exists():
                if process.poll() is not None:
                    raise RuntimeError(f"{run_id} exited before writing a manifest")
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            config = manifest["experiment_config"]
            if config.get("sequences") != sequences:
                process.terminate()
                raise RuntimeError(f"{run_id} selected the wrong sequences")
            if config.get("measurement_code_fingerprints") != EXPECTED_CODE_HASHES:
                process.terminate()
                raise RuntimeError(f"{run_id} recorded the wrong code hashes")
            del pending[run_id]
        if pending:
            time.sleep(1)
    if pending:
        for _, _, process in pending.values():
            process.terminate()
        raise RuntimeError(f"manifest validation timed out: {sorted(pending)}")
    print(json.dumps({
        "scope_validated": True,
        "source_matches_statewise_runs": True,
        "runs": [
            {"run_id": run_id, "domain": domain, "pid": process.pid}
            for run_id, domain, _, process in processes
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
