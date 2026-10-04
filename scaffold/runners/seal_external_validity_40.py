from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "scaffold" / "experiments" / "paper_external_validity_40_v1"
SEAL = PACKAGE / 'package_seal.json'


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replace", action="store_true", help="replace a not-started seal after documentation/audit correction")
    args = parser.parse_args()
    if SEAL.exists() and not args.replace:
        raise FileExistsError(f"refusing to overwrite seal: {SEAL}")
    members = sorted(
        [path for path in (PACKAGE / "cases").glob("*.json")]
        + [
            PACKAGE / "README.md",
            PACKAGE / "closure_audit.json",
            PACKAGE / "launch.ps1",
            PACKAGE / "leakage_audit.json",
            PACKAGE / "paired_matrix.json",
            PACKAGE / "protocol_freeze.json",
            PACKAGE / "snapshot.json",
            PACKAGE / "typedfix_external40_freeze.json",
            PACKAGE / "validate.py",
            ROOT / "scaffold/runners/launch_external_validity_40.py",
            ROOT / "scaffold/runners/prepare_external_validity_40.py",
            ROOT / "scaffold/runners/seal_external_validity_40.py",
        ],
        key=lambda path: path.as_posix(),
    )
    missing = [str(path) for path in members if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing)
    files = {path.relative_to(ROOT).as_posix(): _sha(path) for path in members}
    composite = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    value = {
        "schema_version": "paper-external-validity-package-seal-v1",
        "status": "FROZEN_NOT_STARTED",
        "file_count": len(files),
        "files": files,
        "composite_sha256": composite,
        "snapshot_sha256": _sha(PACKAGE / "snapshot.json"),
        "paired_matrix_sha256": _sha(PACKAGE / "paired_matrix.json"),
        "api_outcomes_observed_before_seal": False,
    }
    SEAL.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
