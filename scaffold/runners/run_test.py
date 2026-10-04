import glob
import argparse
import json
import os
import sys

from scaffold.statewise import config
from scaffold.statewise.evaluation import case_eval

CASES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cases")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true", help="print summaries instead of full episode JSON")
    args = parser.parse_args()
    if not config.FAKE_API:
        print(
            "STATECLARIFY_FAKE_API is false — run_test.py is the deterministic "
            "fake-mode gate. Use run_real.py for the live API.",
            file=sys.stderr,
        )
        sys.exit(2)

    case_paths = sorted(glob.glob(os.path.join(CASES_DIR, "*.json")))
    if not case_paths:
        print(f"No case files found under {CASES_DIR}")
        sys.exit(1)

    all_failures = {}
    scripted_case_paths = []
    skipped_live_only = []
    catches_table = []
    for case_path in case_paths:
        with open(case_path, "r", encoding="utf-8") as f:
            case = json.load(f)
        case_id = case["case_id"]
        if case.get("fake_scripted", True) is False:
            skipped_live_only.append(case_id)
            continue
        scripted_case_paths.append(case_path)

        results, failures = case_eval.evaluate_case(case_path, case)

        print("=" * 64)
        print(f"CASE: {case_id}")
        print("=" * 64)
        if not args.quiet:
            print(json.dumps(results, indent=2, ensure_ascii=False))

        row = case_eval.boring_but_risky_row(results)
        if row is not None:
            catches_table.append((case_id, row[0], row[1]))

        if failures:
            print(f"\n[FAIL] {case_id}: {len(failures)} issue(s)")
            for f in failures:
                print(f"  - {f}")
            all_failures[case_id] = failures
        else:
            print(f"\n[PASS] {case_id}")

    _print_boring_but_risky(catches_table)

    print("\n" + "=" * 64)
    print("SUMMARY")
    print("=" * 64)
    total = len(scripted_case_paths)
    failed = len(all_failures)
    print(f"{total - failed}/{total} cases passed")
    if skipped_live_only:
        print(
            f"{len(skipped_live_only)} live-only Phase 2 cases skipped by the scripted fake gate: "
            + ", ".join(skipped_live_only)
        )
    if all_failures:
        for case_id, failures in all_failures.items():
            print(f"\n{case_id}:")
            for f in failures:
                print(f"  - {f}")
        sys.exit(1)


def _print_boring_but_risky(catches_table):
    print("\n" + "=" * 64)
    print("BORING-BUT-RISKY TABLE (corrupted condition)")
    print("  raw = action-only gate flagged it | pipe = full pipeline intervened")
    print("=" * 64)
    for case_id, raw_caught, pipe_intervened in catches_table:
        print(f"  raw={'Y' if raw_caught else 'N'}  pipe={'Y' if pipe_intervened else 'N'}   {case_id}")


if __name__ == "__main__":
    main()
