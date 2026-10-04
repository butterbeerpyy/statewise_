import argparse
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATASET = "scaffold/experiments/rq5_longitudinal_40_v2"
LOG_DIR = ROOT / "runs" / "rq5_matrix_logs"


BASELINE_ARMS = [
    "correct",
    "corrupted",
    "no_memory",
    "auto_execute",
    "bare_approval",
    "rationale_approval",
    "generic_clarification",
    "safety_sentry",
    "memlineage_trust",
    "oracle_statewise",
]


METHOD_MODELS = [
    ("rq5v2_deepseek_v4pro", 'api_01'),
    ("rq5v2_qwen37max", "qwen"),
]

BASELINE_PROFILE = "rq5v2_gpt56sol"


def shards():
    items = []
    for arm in BASELINE_ARMS:
        items.append({
            "run_id": f"rq5v2_base_{arm}_gpt56sol",
            "arm": arm,
            "profile": BASELINE_PROFILE,
        })
    for profile, tag in METHOD_MODELS:
        items.append({
            "run_id": f"rq5v2_method_{tag}",
            "arm": "statewise_v2_retrieval",
            "profile": profile,
        })
    return items


def command(shard):
    return [
        "python", "scaffold/runners/run_rq5_longitudinal_real.py", DATASET,
        "--run-id", shard["run_id"],
        "--arm", shard["arm"],
        "--api-profile", shard["profile"],
        "--max-concurrency", "1",
        "--max-attempts", "3",
        "--retry-response-contract",
        "--execute",
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", action="store_true", help="print shards and exit")
    parser.add_argument("--run", action="store_true", help="launch the matrix")
    parser.add_argument("--max-parallel", type=int, default=12)
    parser.add_argument("--poll-seconds", type=int, default=60)
    args = parser.parse_args()

    items = shards()
    if args.plan or not args.run:
        print(f"{len(items)} shards, max_parallel={args.max_parallel}")
        for shard in items:
            print(f"  {shard['run_id']:45s} arm={shard['arm']:22s} profile={shard['profile']}")
        print("\nEach shard runs 40 sequences serially (method variants are process-global).")
        return 0

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    pending = list(items)
    running = []
    finished = []

    while pending or running:
        while pending and len(running) < args.max_parallel:
            shard = pending.pop(0)
            out = open(LOG_DIR / f"{shard['run_id']}.stdout.log", "w", encoding="utf-8")
            err = open(LOG_DIR / f"{shard['run_id']}.stderr.log", "w", encoding="utf-8")
            process = subprocess.Popen(
                command(shard), cwd=ROOT, stdout=out, stderr=err, text=True,
            )
            running.append({"shard": shard, "process": process, "out": out, "err": err})
            print(f"[launch] {shard['run_id']} pid={process.pid} "
                  f"({len(running)} running, {len(pending)} queued)", flush=True)

        time.sleep(args.poll_seconds)

        still = []
        for item in running:
            code = item["process"].poll()
            if code is None:
                still.append(item)
                continue
            item["out"].close()
            item["err"].close()
            finished.append({"run_id": item["shard"]["run_id"], "returncode": code})
            print(f"[done] {item['shard']['run_id']} exit={code} "
                  f"({len(finished)}/{len(items)} complete)", flush=True)
        running = still

    print("\n=== summary ===")
    for item in finished:
        flag = "ok" if item["returncode"] == 0 else "FAIL"
        print(f"[{flag}] {item['run_id']} exit={item['returncode']}")
    failures = [item for item in finished if item["returncode"] != 0]
    print(f"\n{len(finished) - len(failures)}/{len(finished)} shards exited 0")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
