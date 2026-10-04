from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scaffold.runners import method_freeze


PROJECT_DIR = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_DIR / "scaffold" / "experiments" / "statewise_v1_freeze.json"
SELECTED_VARIANT = "combined"
VARIANT_FILES = (
    "scaffold/statewise/experiments/targeted_variants.py",
)


def file_hashes():
    return {
        relative: hashlib.sha256((PROJECT_DIR / relative).read_bytes()).hexdigest()
        for relative in VARIANT_FILES
    }


def method_fingerprint(hashes=None, base_fingerprint=None):
    hashes = hashes or file_hashes()
    base_fingerprint = base_fingerprint or method_freeze.verify()["actual_fingerprint"]
    digest = hashlib.sha256()
    for value in ("StateWise-v1", SELECTED_VARIANT, base_fingerprint):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    for relative in VARIANT_FILES:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashes[relative].encode("ascii"))
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def load_manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def verify():
    base = method_freeze.verify()
    manifest = load_manifest()
    actual_hashes = file_hashes()
    changed = [
        relative
        for relative in VARIANT_FILES
        if manifest.get("files", {}).get(relative) != actual_hashes[relative]
    ]
    unexpected = sorted(set(manifest.get("files", {})) - set(VARIANT_FILES))
    actual_fingerprint = method_fingerprint(
        actual_hashes, base_fingerprint=base["actual_fingerprint"]
    )
    valid = (
        base["valid"]
        and manifest.get("selected_variant") == SELECTED_VARIANT
        and manifest.get("base_fingerprint") == base["actual_fingerprint"]
        and not changed
        and not unexpected
        and manifest.get("fingerprint") == actual_fingerprint
    )
    return {
        "version": manifest.get("version"),
        "valid": valid,
        "selected_variant": SELECTED_VARIANT,
        "base_valid": base["valid"],
        "base_fingerprint": base["actual_fingerprint"],
        "expected_fingerprint": manifest.get("fingerprint"),
        "actual_fingerprint": actual_fingerprint,
        "changed_files": changed,
        "unexpected_manifest_files": unexpected,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", action="store_true")
    args = parser.parse_args()
    if args.current:
        base = method_freeze.verify()
        hashes = file_hashes()
        output = {
            "version": "StateWise-v1",
            "selected_variant": SELECTED_VARIANT,
            "base_fingerprint": base["actual_fingerprint"],
            "fingerprint": method_fingerprint(
                hashes, base_fingerprint=base["actual_fingerprint"]
            ),
            "files": hashes,
        }
        status = 0 if base["valid"] else 1
    else:
        output = verify()
        status = 0 if output["valid"] else 1
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
