from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scaffold/experiments/provenance_trust_48_v1"
OUTPUT = ROOT / "scaffold/experiments/provenance_trust_canary_v1"
PER_CELL = 2


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    snapshot = json.loads((SOURCE / "snapshot.json").read_text(encoding="utf-8"))
    by_cell: dict[str, list[dict]] = {}
    for entry in snapshot["cases"]:
        by_cell.setdefault(entry["cell"], []).append(entry)


    keep_bases: list[str] | None = None
    picked: list[dict] = []
    for cell in sorted(by_cell):
        items = sorted(by_cell[cell], key=lambda entry: entry["case_id"])
        cases = [
            json.loads(
                (SOURCE / "cases" / item["file"]).read_text(encoding="utf-8")
            )
            for item in items
        ]
        if keep_bases is None:
            keep_bases = sorted(
                case["provenance_trust_cell"]["base_case_id"] for case in cases
            )[:PER_CELL]
        for item, case in zip(items, cases):
            if case["provenance_trust_cell"]["base_case_id"] in keep_bases:
                picked.append(item)

    print("canary cases: %d" % len(picked))
    for item in picked:
        print("   %-6s %s" % (item["cell"], item["case_id"]))

    if not args.write:
        print("\ndry run: pass --write to materialize")
        return 0

    (OUTPUT / "cases").mkdir(parents=True, exist_ok=True)
    entries = []
    for item in picked:
        payload = (SOURCE / "cases" / item["file"]).read_bytes()
        (OUTPUT / "cases" / item["file"]).write_bytes(payload)
        entries.append({**item, "sha256": _sha(OUTPUT / "cases" / item["file"])})

    out = {
        **snapshot,
        "snapshot_id": "provenance_trust_canary_v1",
        "purpose": "canary subset of provenance_trust_48_v1; not paper-facing",
        "case_count": len(entries),
        "cases": entries,
        "parent_snapshot": "provenance_trust_48_v1",
    }
    (OUTPUT / "snapshot.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("\nwrote %s" % OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
