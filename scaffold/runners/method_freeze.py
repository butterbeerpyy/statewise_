from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_DIR / "scaffold" / "experiments" / "statewise_v0_freeze.json"

METHOD_FILES = (
    "scaffold/statewise/agents/human_simulator.py",
    "scaffold/statewise/agents/permission_simulator.py",
    "scaffold/statewise/agents/planner.py",
    "scaffold/statewise/core/attribution.py",
    "scaffold/statewise/core/critical_detect.py",
    "scaffold/statewise/core/episode_loop.py",
    "scaffold/statewise/core/extract_states.py",
    "scaffold/statewise/core/interceptor.py",
    "scaffold/statewise/core/main_loop.py",
    "scaffold/statewise/core/question_gen.py",
    "scaffold/statewise/core/reliability.py",
    "scaffold/statewise/core/residual_risk.py",
    "scaffold/statewise/core/route.py",
    "scaffold/statewise/core/state_action_gate.py",
    "scaffold/statewise/experiments/intervention_value.py",
    "scaffold/statewise/memory/memory_repair.py",
    "scaffold/statewise/memory/memory_store.py",
    "scaffold/statewise/runtime/tools.py",
)


def file_hashes():
    hashes = {}
    for relative in METHOD_FILES:
        data = (PROJECT_DIR / relative).read_bytes()
        hashes[relative] = hashlib.sha256(data).hexdigest()
    return hashes


def method_fingerprint(hashes=None):
    hashes = hashes or file_hashes()
    digest = hashlib.sha256()
    for relative in METHOD_FILES:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashes[relative].encode("ascii"))
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def load_manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def verify():
    manifest = load_manifest()
    actual_hashes = file_hashes()
    changed = [
        relative
        for relative in METHOD_FILES
        if manifest.get("files", {}).get(relative) != actual_hashes[relative]
    ]
    missing_from_boundary = sorted(set(manifest.get("files", {})) - set(METHOD_FILES))
    actual_fingerprint = method_fingerprint(actual_hashes)
    return {
        "version": manifest.get("version"),
        "valid": (
            not changed
            and not missing_from_boundary
            and manifest.get("fingerprint") == actual_fingerprint
        ),
        "expected_fingerprint": manifest.get("fingerprint"),
        "actual_fingerprint": actual_fingerprint,
        "changed_files": changed,
        "unexpected_manifest_files": missing_from_boundary,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--current",
        action="store_true",
        help="print current hashes before the initial manifest is committed",
    )
    args = parser.parse_args()
    if args.current:
        hashes = file_hashes()
        output = {
            "version": "StateWise-v0",
            "fingerprint": method_fingerprint(hashes),
            "files": hashes,
        }
        status = 0
    else:
        output = verify()
        status = 0 if output["valid"] else 1
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
