import json
import sys
from datetime import datetime
from pathlib import Path


def _intervals(manifest):
    for episode in manifest["episodes"].values():
        for attempt in episode["attempts"]:
            yield (
                datetime.fromisoformat(attempt["started_at"]),
                datetime.fromisoformat(attempt["finished_at"]),
                episode["spec"]["episode_id"],
            )


def _measurements(run_dir):

    manifest = json.loads((Path(run_dir) / "manifest.json").read_text(encoding="utf-8"))
    result = {}
    for episode in manifest["episodes"].values():
        last = episode["attempts"][-1]
        result[episode["spec"]["episode_id"]] = {
            "status": episode["status"],
            "summary": (last.get("result") or {}).get("summary"),
            "failure_kind": (last.get("failure") or {}).get("kind"),
        }
    return result


def compare(run_a, run_b):
    left = _measurements(run_a)
    right = _measurements(run_b)
    print(f"episodes_a             : {len(left)}")
    print(f"episodes_b             : {len(right)}")
    print(f"same_episode_set       : {set(left) == set(right)}")
    only_a = sorted(set(left) - set(right))
    only_b = sorted(set(right) - set(left))
    if only_a:
        print(f"only_in_a              : {only_a}")
    if only_b:
        print(f"only_in_b              : {only_b}")
    differing = sorted(k for k in set(left) & set(right) if left[k] != right[k])
    print(f"differing_measurements : {len(differing)}")
    for key in differing:
        print(f"  {key}")
    if not differing and not only_a and not only_b:
        print("MATCH: concurrent run reproduces serial measurements exactly")
        return 0
    return 1


def main(argv):
    if len(argv) == 3:
        return compare(argv[1], argv[2])
    if len(argv) != 2:
        raise SystemExit("usage: check_parallel_overlap <run_dir> [<run_dir_b>]")
    manifest_path = Path(argv[1]) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    spans = sorted(_intervals(manifest))
    if not spans:
        raise SystemExit("no attempts recorded")


    peak = max(
        sum(1 for start, end, _ in spans if start <= probe < end)
        for probe, _, _ in spans
    )
    wall = (max(end for _, end, _ in spans) - min(s for s, _, _ in spans)).total_seconds()
    serial = sum((end - start).total_seconds() for start, end, _ in spans)

    configured = manifest["experiment_config"].get("runtime_concurrency")
    print(f"configured_concurrency : {configured}")
    print(f"attempts               : {len(spans)}")
    print(f"peak_in_flight         : {peak}")
    print(f"wall_span_seconds      : {wall:.2f}")
    print(f"sum_attempt_seconds    : {serial:.2f}")
    if wall > 0:
        print(f"observed_speedup       : {serial / wall:.2f}x")


    succeeded = [
        (episode["spec"]["episode_id"], attempt.get("result") or {})
        for episode in manifest["episodes"].values()
        for attempt in episode["attempts"]
        if attempt["status"] == "SUCCEEDED"
    ]
    fake = manifest["experiment_config"].get("fake_api")
    print(f"succeeded_attempts     : {len(succeeded)}")
    print(f"fake_api               : {fake}")
    for name, result in succeeded:
        calls = result.get("api_metrics") or []
        print(f"  {name}: api_calls={len(calls)}")
    if fake and any(result.get("api_metrics") for _, result in succeeded):
        print("WARNING: fake run recorded API metrics; expected none")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
