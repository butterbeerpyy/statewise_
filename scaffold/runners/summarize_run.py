import json
import sys
from collections import Counter
from pathlib import Path


def summarize(run_dir):
    run_path = Path(run_dir)
    manifest = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))
    config = manifest.get("experiment_config", {})
    episodes = manifest.get("episodes", {})

    print(f"=== {run_path.name}")
    print(f"  status        : {manifest.get('status')}")
    print(f"  model         : {config.get('model')}  profile={config.get('api_profile')}")
    print(f"  fake_api      : {config.get('fake_api')}")
    print(f"  concurrency   : {config.get('runtime_concurrency')}")
    print(f"  arms          : {config.get('arms')}")
    print(f"  trials        : {config.get('trials')}")
    print(f"  episodes      : {len(episodes)}")
    print(f"  status_counts : {dict(Counter(e['status'] for e in episodes.values()))}")


    failures = Counter()
    for episode in episodes.values():
        for attempt in episode.get("attempts", []):
            failure = attempt.get("failure")
            if failure:
                failures[(failure.get("kind"), failure.get("error_type"))] += 1
    if failures:
        print("  failure_kinds :")
        for (kind, error_type), count in failures.most_common():
            print(f"      {kind} / {error_type}: {count}")

    summary_path = run_path / "pilot_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        for arm, block in sorted((summary.get("arms") or {}).items()):
            if isinstance(block, dict):
                keys = ("episodes", "task_success", "safety_violation", "questions")
                shown = {k: block.get(k) for k in keys if k in block}
                print(f"  arm {arm}: {shown or block}")
    else:
        print("  pilot_summary : MISSING (run did not reach aggregation)")
    for note in sorted(run_path.glob("*.md")):
        print(f"  NOTE FILE     : {note.name}")


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: summarize_run <run_dir> [<run_dir> ...]")
    for run_dir in argv[1:]:
        summarize(run_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
