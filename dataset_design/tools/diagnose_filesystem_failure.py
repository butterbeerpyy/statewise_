import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs" / "rq5_longitudinal"

run_ids = sys.argv[1:] or ["rq5v2_method_qwen", "rq5v2_method_deepseek"]

for run_id in run_ids:
    manifest_path = RUNS / run_id / "manifest.json"
    if not manifest_path.exists():
        print(f"{run_id}: no manifest")
        continue
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    episodes = manifest.get("episodes") or {}
    episodes = list(episodes.values()) if isinstance(episodes, dict) else episodes

    filesystem_eps = [
        e for e in episodes
        if isinstance(e, dict) and "filesystem" in e.get("spec", {}).get("episode_id", "")
    ]
    print(f"\n=== {run_id}: {len(filesystem_eps)} filesystem episodes")

    for ep in filesystem_eps:
        spec_id = ep.get("spec", {}).get("episode_id", "")
        status = ep.get("status")
        attempts = ep.get("attempts") or []
        last = attempts[-1] if attempts else {}
        payload = last.get("payload") or {}
        task_results = payload.get("task_results") or []

        schema_errors = []
        empty_attribution = 0
        terminal_states = []

        for task in task_results:
            terminal_states.append(str(task.get("terminal_state") or "?"))
            for err in task.get("action_schema_errors") or []:
                schema_errors.append(str(err)[:80])
            attribution = task.get("attribution") or {}
            if not (attribution.get("support_states") or attribution.get("critical_states")):
                empty_attribution += 1

        print(f"  {spec_id[:40]:40s} {status:16s} tasks={len(task_results)}")
        if terminal_states:
            print(f"    terminal: {collections.Counter(terminal_states)}")
        if empty_attribution:
            print(f"    empty attribution: {empty_attribution}/{len(task_results)}")
        if schema_errors:
            print(f"    schema errors: {collections.Counter(schema_errors)}")
