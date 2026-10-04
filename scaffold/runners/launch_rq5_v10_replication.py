from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
METHOD_ROOT = ROOT.parent / 'statewise'
RUNNER = METHOD_ROOT / "scaffold/runners/run_rq5_longitudinal_real.py"
DATASET = ROOT / "scaffold/experiments/rq5_longitudinal_40_v2"
OUTPUT = Path('runs/')
STATUS = ROOT / 'paper_experiments/results/rq5/RQ5_V10_REPLICATION3_STATUS.json'
DATASET_SHA = "a871a91427dd4a5bead0115be695bb74df28a660b25990103cdece681b4b7a62"
DOMAINS = {"env": "environment", "git": "git", "db": "database", "dep": "deployment"}
ARMS = {
    "fin": "statewise_v2_contract_corrected_typedfix",
    "mem": "memlineage_trust",
    "saf": "safety_sentry",
    "ask": "ask_or_assume",
}
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


def validate() -> None:
    mismatches = {}
    for relative, expected in EXPECTED_CODE_HASHES.items():
        path = METHOD_ROOT / relative
        actual = sha256(path) if path.is_file() else None
        if actual != expected:
            mismatches[relative] = {"expected": expected, "actual": actual}
    if mismatches:
        raise RuntimeError(f"frozen measurement code mismatch: {mismatches}")
    manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("composite_sha256") != DATASET_SHA:
        raise RuntimeError("frozen RQ5 dataset SHA mismatch")


def sequence_ids(domain: str) -> list[str]:
    return [f"seq_{domain}_{index:03d}" for index in range(1, 9)]


def command(run_id: str, arm: str, sequences: list[str]) -> list[str]:
    args = [
        sys.executable, str(RUNNER), str(DATASET),
        "--run-id", run_id,
        "--output-root", str(OUTPUT),
        "--arm", arm,
        "--api-profile", "api_02",
        "--max-concurrency", "1",
        "--max-attempts", "3",
        "--execute",
    ]
    for sequence_id in sequences:
        args.extend(("--sequence-id", sequence_id))
    return args


def write_status(payload: dict) -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    validate()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    launched = []
    for domain_code, domain in DOMAINS.items():
        selected = sequence_ids(domain)
        for arm_code, arm in ARMS.items():
            run_id = f"r5v10-rep3-{domain_code}-{arm_code}"
            stdout_path = OUTPUT / f"{run_id}.stdout.log"
            stderr_path = OUTPUT / f"{run_id}.stderr.log"
            stdout = stdout_path.open("a", encoding="utf-8")
            stderr = stderr_path.open("a", encoding="utf-8")
            process = subprocess.Popen(
                command(run_id, arm, selected),
                cwd=METHOD_ROOT,
                stdout=stdout,
                stderr=stderr,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            stdout.close()
            stderr.close()
            launched.append({
                "run_id": run_id,
                "domain": domain,
                "arm": arm,
                "sequence_ids": selected,
                "pid": process.pid,
                "stdout": str(stdout_path),
                "stderr": str(stderr_path),
            })

    pending = {item["run_id"]: item for item in launched}
    deadline = time.monotonic() + 180
    while pending and time.monotonic() < deadline:
        for run_id, item in list(pending.items()):
            manifest_path = OUTPUT / run_id / "manifest.json"
            if not manifest_path.exists():
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            config = manifest.get("experiment_config") or {}
            if config.get("sequences") != item["sequence_ids"]:
                raise RuntimeError(f"{run_id}: selected sequence mismatch")
            if config.get("arms") != [item["arm"]]:
                raise RuntimeError(f"{run_id}: selected arm mismatch")


            if (manifest.get("manager") or {}).get("max_concurrency") != 1:
                raise RuntimeError(f"{run_id}: serial worker contract mismatch")
            if config.get("measurement_code_fingerprints") != EXPECTED_CODE_HASHES:
                raise RuntimeError(f"{run_id}: measurement hash mismatch")
            item["manifest_validated"] = True
            del pending[run_id]
        if pending:
            time.sleep(2)
    if pending:
        raise RuntimeError(f"manifest validation timeout: {sorted(pending)}")
    payload = {
        "schema_version": "rq5-v10-replication-status-v1",
        "status": "RUNNING",
        "launched_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "independent same-model replication 3; rep2 is engineering-invalid and excluded",
        "dataset_composite_sha256": DATASET_SHA,
        "model": "gpt-5.6-sol",
        "temperature": 0.0,
        "worker_isolation": "one sequence worker per process; 16 processes",
        "paper_methods": list(ARMS.values()),
        "runs": launched,
    }
    write_status(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
