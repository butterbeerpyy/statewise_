import argparse
import pathlib
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATASET = "scaffold/experiments/rq5_longitudinal_40_v2"
LOG_DIR = ROOT / "runs" / "rq5_matrix_logs"
PROFILE = "rq5v2_claude_fable5"
ARM = "statewise_v2_retrieval"
SHARD_COUNT = 4

sequence_ids = sorted(
    p.stem for p in (ROOT / DATASET).glob("seq_*.json")
)
assert len(sequence_ids) == 40, f"expected 40 sequences, found {len(sequence_ids)}"

shards = []
for index in range(SHARD_COUNT):
    assigned = [s for i, s in enumerate(sequence_ids) if i % SHARD_COUNT == index]
    shards.append({
        "run_id": f"rq5v2_method_claude_temp1_s{index}",
        "sequence_ids": assigned,
    })


def build_command(shard):
    command = [
        "python", "scaffold/runners/run_rq5_longitudinal_real.py", DATASET,
        "--run-id", shard["run_id"], "--arm", ARM, "--api-profile", PROFILE,
        "--max-concurrency", "1", "--max-attempts", "3",
        "--retry-response-contract", "--execute",
    ]
    for sequence_id in shard["sequence_ids"]:
        command += ["--sequence-id", sequence_id]
    return command


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", action="store_true", help="print shards and exit")
    parser.add_argument("--run", action="store_true", help="launch the shards")
    parser.add_argument("--poll-seconds", type=int, default=120)
    args = parser.parse_args()

    if not args.run:
        print(f"{len(shards)} shards, {len(sequence_ids)} sequences total")
        for shard in shards:
            domains = {}
            for sequence_id in shard["sequence_ids"]:
                domain = sequence_id.split("_")[1]
                domains[domain] = domains.get(domain, 0) + 1
            print(f"  {shard['run_id']}: {len(shard['sequence_ids'])} seqs {domains}")
        if not args.plan:
            print("\nnothing launched; pass --run to execute")
        return 0

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    running = []
    for shard in shards:
        stdout = (LOG_DIR / f"{shard['run_id']}.stdout.log").open("w", encoding="utf-8")
        stderr = (LOG_DIR / f"{shard['run_id']}.stderr.log").open("w", encoding="utf-8")
        process = subprocess.Popen(
            build_command(shard), cwd=ROOT, stdout=stdout, stderr=stderr
        )
        running.append({"shard": shard, "process": process, "handles": (stdout, stderr)})
        print(f"[start] {shard['run_id']} pid={process.pid}", flush=True)

    results = []
    while running:
        time.sleep(args.poll_seconds)
        still = []
        for item in running:
            code = item["process"].poll()
            if code is None:
                still.append(item)
                continue
            for handle in item["handles"]:
                handle.close()
            results.append((item["shard"]["run_id"], code))
            print(
                f"[done] {item['shard']['run_id']} exit={code} "
                f"({len(results)}/{len(shards)} complete)",
                flush=True,
            )
        running = still

    print("\n=== summary ===")
    for run_id, code in results:
        print(f"{'[ok]' if code == 0 else '[FAIL]'} {run_id} exit={code}")
    return 0 if all(code == 0 for _, code in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
