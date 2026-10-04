import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path


def _reasons(episode):

    found = []
    if episode.get("status") != "SUCCEEDED":
        found.append("infra_failure")
    attempt = (episode.get("attempts") or [{}])[-1]
    summary = (attempt.get("result") or {}).get("summary") or {}
    if not summary:
        return found or ["no_summary"]

    if summary.get("risk_adjusted_task_success") is False:
        found.append("task_failure")
    if summary.get("safety_violation"):
        found.append("safety_violation")


    for metric in ("attribution_precision", "attribution_recall"):
        value = summary.get(metric)
        if value is not None and value == 0:
            found.append("attribution_miss")
            break

    mutation = summary.get("unnecessary_mutation") or {}
    if mutation.get("unnecessary_mutation_count"):
        found.append("unnecessary_mutation")

    if summary.get("status") in {"STEP_LIMIT", "SAFE_ABORT", "ABSTAIN"}:
        found.append("nonterminal_status")
    return found


def export(run_dir, out_dir, only=None):
    run_path = Path(run_dir)
    manifest = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    index = []
    tally = Counter()
    for episode in manifest["episodes"].values():
        reasons = _reasons(episode)
        if only:
            reasons = [reason for reason in reasons if reason == only]
        if not reasons:
            continue
        tally.update(reasons)

        episode_id = episode["spec"]["episode_id"]
        attempt = (episode.get("attempts") or [{}])[-1]
        summary = (attempt.get("result") or {}).get("summary") or {}
        target = out_path / episode_id.replace("/", "_")
        target.mkdir(parents=True, exist_ok=True)


        (target / "episode_manifest.json").write_text(
            json.dumps(episode, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        raw = (attempt.get("result") or {}).get("raw_result")
        if raw is not None:
            (target / "raw_result.json").write_text(
                json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        api_metrics = (attempt.get("result") or {}).get("api_metrics")
        if api_metrics:
            (target / "api_metrics.json").write_text(
                json.dumps(api_metrics, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )


        workspace = attempt.get("workspace")
        if workspace and Path(workspace).is_dir():
            shutil.copytree(
                workspace, target / "workspace", dirs_exist_ok=True,
            )


        for checkpoint in (run_path / "checkpoints").glob(f"*{episode['spec']['case_id']}*"):
            shutil.copy2(checkpoint, target / checkpoint.name)

        index.append(
            {
                "episode_id": episode_id,
                "case_id": episode["spec"]["case_id"],
                "arm": episode["spec"].get("condition"),
                "domain": (episode["spec"].get("payload") or {}).get("domain"),
                "reasons": reasons,
                "episode_status": episode.get("status"),
                "runtime_status": summary.get("status"),
                "terminal_reason": summary.get("terminal_reason"),
                "task_success": summary.get("task_success"),
                "risk_adjusted_task_success": summary.get("risk_adjusted_task_success"),
                "safety_violation": summary.get("safety_violation"),
                "attribution_precision": summary.get("attribution_precision"),
                "attribution_recall": summary.get("attribution_recall"),
                "repair_performed": summary.get("repair_performed"),
                "repair_correct": summary.get("repair_correct"),
                "steps": summary.get("steps"),
                "replan_count": summary.get("replan_count"),
                "baseline_decision": summary.get("baseline_decision"),
                "initial_action": summary.get("initial_action"),
                "final_action": summary.get("final_action"),
                "artifacts": sorted(p.name for p in target.iterdir()),
            }
        )

    index.sort(key=lambda item: (item["reasons"], item["episode_id"]))
    (out_path / "index.json").write_text(
        json.dumps(
            {
                "source_run": str(run_path),
                "model": manifest.get("experiment_config", {}).get("model"),
                "arms": manifest.get("experiment_config", {}).get("arms"),
                "total_episodes": len(manifest["episodes"]),
                "exported": len(index),
                "reason_counts": dict(tally),
                "episodes": index,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"source        : {run_path}")
    print(f"total_episodes: {len(manifest['episodes'])}")
    print(f"exported      : {len(index)}")
    print(f"reason_counts : {dict(tally)}")
    print(f"output        : {out_path}")
    for item in index:
        print(f"  {item['episode_id']}: {','.join(item['reasons'])}")
    return 0


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--only", default=None, help="export just one reason category"
    )
    args = parser.parse_args(argv[1:])
    out = args.out or f"runs/debug_failed_cases/{Path(args.run_dir).name}"
    return export(args.run_dir, out, args.only)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
