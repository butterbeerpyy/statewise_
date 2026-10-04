from __future__ import annotations

import argparse
import json
from pathlib import Path


def _case_ids(payload):
    for key in ("cases", "entries", "case_ids", "items"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            if isinstance(value[0], str):
                return list(value)
            for field in ("case_id", "id", "case_file", "path"):
                if field in value[0]:
                    return [str(item.get(field)) for item in value]
    return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("target_tree", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.dataset.read_text(encoding="utf-8"))
    ids = _case_ids(payload)
    print(f"dataset: {args.dataset.name}")
    print(f"top-level keys: {sorted(payload)}")
    print(f"case entries: {len(ids)}")
    if not ids:
        print("could not locate a case list; inspect the keys above")
        return 1

    cases_dir = args.target_tree / "scaffold" / "cases"
    missing = []
    for raw in ids:
        stem = Path(raw).stem
        if not (cases_dir / f"{stem}.json").exists():
            missing.append(stem)
    print(f"target tree: {args.target_tree}")
    print(f"present: {len(ids) - len(missing)}/{len(ids)}")
    if missing:
        print(f"MISSING {len(missing)}:")
        for name in missing[:20]:
            print(f"  {name}")
    else:
        print("all referenced cases exist in the target tree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
