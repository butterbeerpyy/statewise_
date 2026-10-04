from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scaffold/runners/run_rq5_longitudinal_real.py"
DATASET = ROOT / "scaffold/experiments/rq5_longitudinal_40_v2"
OUTPUT = Path('runs/')
DOMAINS = {"env": "environment", "git": "git", "db": "database", "dep": "deployment"}
ARMS = {"mem": "memlineage_trust", "saf": "safety_sentry", "ask": "ask_or_assume"}


def expected_sequences(domain: str) -> list[str]:
    return [f"seq_{domain}_{index:03d}" for index in range(1, 9)]


def command(run_id: str, arm: str, sequences: list[str]) -> list[str]:
    args = [
        sys.executable,
        str(RUNNER),
        str(DATASET),
        "--run-id",
        run_id,
        "--output-root",
        str(OUTPUT),
        "--arm",
        arm,
        "--api-profile",
        "rightapi_gpt56sol",
        "--max-concurrency",
        "1",
        "--max-attempts",
        "3",
        "--retry-response-contract",
        "--execute",
    ]
    for sequence_id in sequences:
        args.extend(("--sequence-id", sequence_id))
    return args


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", action="append", choices=sorted(DOMAINS))
    parser.add_argument("--validation-timeout", type=int, default=90)
    args = parser.parse_args()
    if args.validation_timeout < 1:
        raise SystemExit("--validation-timeout must be positive")
    selected_domains = {
        code: domain for code, domain in DOMAINS.items()
        if not args.domain or code in args.domain
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    processes: list[tuple[str, str, list[str], subprocess.Popen]] = []
    for domain_code, domain in selected_domains.items():
        sequences = expected_sequences(domain)
        for arm_code, arm in ARMS.items():
            run_id = f"r5v10-{domain_code}-{arm_code}-b2"
            stdout = (OUTPUT / f"{run_id}.stdout.log").open("w", encoding="utf-8")
            stderr = (OUTPUT / f"{run_id}.stderr.log").open("w", encoding="utf-8")
            process = subprocess.Popen(
                command(run_id, arm, sequences),
                cwd=ROOT,
                stdout=stdout,
                stderr=stderr,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            stdout.close()
            stderr.close()
            processes.append((run_id, domain, sequences, process))

    deadline = time.monotonic() + args.validation_timeout
    pending = {item[0]: item for item in processes}
    while pending and time.monotonic() < deadline:
        for run_id, item in list(pending.items()):
            _, domain, sequences, process = item
            manifest_path = OUTPUT / run_id / "manifest.json"
            if not manifest_path.exists():
                if process.poll() is not None:
                    raise RuntimeError(f"{run_id} exited before writing a manifest")
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            selected = manifest["experiment_config"]["sequences"]
            if selected != sequences or any(not value.startswith(f"seq_{domain}_") for value in selected):
                process.terminate()
                raise RuntimeError(f"{run_id} selected the wrong sequences: {selected}")
            del pending[run_id]
        if pending:
            time.sleep(1)

    if pending:
        for _, _, _, process in pending.values():
            process.terminate()
        raise RuntimeError(f"manifest validation timed out: {sorted(pending)}")

    print(json.dumps({
        "launched": [
            {"run_id": run_id, "domain": domain, "sequences": sequences, "pid": process.pid}
            for run_id, domain, sequences, process in processes
        ],
        "scope_validated": True,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
