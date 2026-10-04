import argparse
import glob
import json
import os
import sys
import subprocess
import time
from pathlib import Path

CASES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cases")


def get_all_case_ids():

    case_paths = sorted(glob.glob(os.path.join(CASES_DIR, "*.json")))
    case_ids = []
    for path in case_paths:
        with open(path, "r", encoding="utf-8") as f:
            case = json.load(f)
        if not case.get("fake_scripted", True):
            case_ids.append(case["case_id"])
    return case_ids


def split_into_groups(items, num_groups):

    groups = [[] for _ in range(num_groups)]
    for i, item in enumerate(items):
        groups[i % num_groups].append(item)
    return groups


def run_worker(worker_id, case_ids, trials, quiet):

    cmd = [
        sys.executable,
        "-m",
        "scaffold.runners.run_real",
        "--trials",
        str(trials),
    ]

    for case_id in case_ids:
        cmd.extend(["--case", case_id])

    if quiet:
        cmd.append("--quiet")

    print(f"[Worker {worker_id}] Starting with {len(case_ids)} cases: {', '.join(case_ids[:3])}{'...' if len(case_ids) > 3 else ''}")

    start_time = time.time()
    result = subprocess.run(cmd, capture_output=False, text=True)
    elapsed = time.time() - start_time

    if result.returncode == 0:
        print(f"[Worker {worker_id}] OK completed in {elapsed:.1f}s")
    else:
        print(
            f"[Worker {worker_id}] FAILED exit={result.returncode} "
            f"after {elapsed:.1f}s"
        )

    return result.returncode


def run_serial(case_ids, trials, quiet):

    cmd = [
        sys.executable,
        "-m",
        "scaffold.runners.run_real",
        "--trials",
        str(trials),
    ]
    for case_id in case_ids:
        cmd.extend(["--case", case_id])
    if quiet:
        cmd.append("--quiet")

    print(f"Running serial mode with {len(case_ids)} cases")
    start_time = time.time()
    result = subprocess.run(cmd, capture_output=False, text=True)
    elapsed = time.time() - start_time
    print("\n" + "=" * 64)
    print("SERIAL EXECUTION SUMMARY")
    print("=" * 64)
    print(f"Total time: {elapsed:.1f}s ({elapsed/60:.1f} minutes)")
    print(f"Total cases: {len(case_ids)}")
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="Run real API tests in parallel")
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Number of parallel workers (default: 3)",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=1,
        help="Number of trials per case (default: 1)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Pass --quiet to worker processes",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="run only this live-only case id; repeatable",
    )
    parser.add_argument(
        "--serial",
        action="store_true",
        help="run all selected cases through one run_real.py process",
    )
    args = parser.parse_args()


    case_ids = get_all_case_ids()
    if not case_ids:
        print(f"No live-only cases found in {CASES_DIR}")
        sys.exit(1)
    if args.case_ids:
        wanted = set(args.case_ids)
        available = set(case_ids)
        unknown = sorted(wanted - available)
        if unknown:
            print(
                f"Requested case ids are absent or not live-only: {unknown}",
                file=sys.stderr,
            )
            sys.exit(2)
        case_ids = [case_id for case_id in case_ids if case_id in wanted]

    if args.serial or args.workers == 1:
        if args.workers < 1:
            print("--workers must be positive", file=sys.stderr)
            sys.exit(2)
        sys.exit(run_serial(case_ids, args.trials, args.quiet))

    if args.workers < 1:
        print("--workers must be positive", file=sys.stderr)
        sys.exit(2)

    print(f"Found {len(case_ids)} live-only cases")
    print(f"Splitting into {args.workers} workers")


    groups = split_into_groups(case_ids, args.workers)


    for i, group in enumerate(groups):
        print(f"  Worker {i}: {len(group)} cases")

    print("\nStarting parallel execution...")
    print("=" * 64)

    start_time = time.time()


    processes = []
    for i, group in enumerate(groups):
        if not group:
            continue

        cmd = [
            "conda",
            "run",
            "-n",
            "nightly",
            "--no-capture-output",
            "python",
            "-m",
            "scaffold.runners.run_real",
            "--trials",
            str(args.trials),
        ]

        for case_id in group:
            cmd.extend(["--case", case_id])

        if args.quiet:
            cmd.append("--quiet")


        log_file = open(f"worker_{i}.log", "w", encoding="utf-8")
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, text=True)
        processes.append((i, proc, log_file))


    exit_codes = []
    for worker_id, proc, log_file in processes:
        proc.wait()
        log_file.close()
        exit_codes.append(proc.returncode)


        print(f"\n{'=' * 64}")
        print(f"Worker {worker_id} output:")
        print('=' * 64)
        with open(f"worker_{worker_id}.log", "r", encoding="utf-8") as f:
            print(f.read())

    elapsed = time.time() - start_time

    print("\n" + "=" * 64)
    print("PARALLEL EXECUTION SUMMARY")
    print("=" * 64)
    print(f"Total time: {elapsed:.1f}s ({elapsed/60:.1f} minutes)")
    print(f"Workers: {args.workers}")
    print(f"Total cases: {len(case_ids)}")

    failed_workers = [i for i, code in enumerate(exit_codes) if code != 0]
    if failed_workers:
        print(f"\nFAILED {len(failed_workers)} worker(s): {failed_workers}")
        sys.exit(1)
    else:
        print("\nOK all workers completed successfully")


if __name__ == "__main__":
    main()
