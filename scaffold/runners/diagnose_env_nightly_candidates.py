from __future__ import annotations

import copy
import json
import tempfile

from scaffold.statewise.core import extract_states, main_loop
from scaffold.statewise.experiments import pilot_conditions
from scaffold.runners import method_freeze


CASE_PATH = str(
    method_freeze.PROJECT_DIR / "scaffold" / "cases" / "case_env_nightly.json"
)


def main():
    observed = []
    original_extract = extract_states.extract

    def traced(*args, **kwargs):
        result = original_extract(*args, **kwargs)
        state = args[1] if len(args) > 1 else kwargs.get("state")
        case_id = args[2] if len(args) > 2 else kwargs.get("case_id", "default")
        suffix = args[3] if len(args) > 3 else kwargs.get(
            "stage_suffix", "extract_states"
        )
        observed.append({
            "stage": f"{case_id}:{suffix}",
            "state_ids": sorted(state or {}),
            "state_entries": [
                f"{key}: {entry.get('key')!r} = {entry.get('value')!r}"
                for key, entry in sorted((state or {}).items())
            ],
            "candidates": [
                {"id": item.get("id"), "source": item.get("source")}
                for item in result
            ],
        })
        return result

    case = main_loop.load_case(CASE_PATH)
    shared = pilot_conditions.build_proposal(case, "corrupted")
    extract_states.extract = traced
    try:
        with tempfile.TemporaryDirectory() as episode_root:
            try:
                pilot_conditions.run_executable_arm(
                    CASE_PATH,
                    "oracle_statewise",
                    episode_root=episode_root,
                    initial_proposal=copy.deepcopy(shared),
                )
            except KeyError as error:
                print(f"stopped at: {error}\n")
    finally:
        extract_states.extract = original_extract

    for record in observed:
        print(f"stage={record['stage']}")
        for line in record.get("state_entries", []):
            print(f"  state {line}")
        for item in record["candidates"]:
            print(f"  {item['id']:<4} {item['source']}")
    print()
    print(json.dumps({"extract_calls": len(observed)}))


if __name__ == "__main__":
    raise SystemExit(main())
