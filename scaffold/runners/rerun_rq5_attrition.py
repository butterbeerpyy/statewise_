from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


ATTRITED = (
    ("generic_clarification", "seq_environment_002"),
    ("safety_sentry", "seq_deployment_002"),
    ("safety_sentry", "seq_environment_002"),
    ("oracle_statewise", "seq_database_004"),
    ("oracle_statewise", "seq_deployment_004"),
    ("oracle_statewise", "seq_git_001"),
)


def dataset_is_valid(dataset: Path) -> tuple[bool, str]:
    manifest = dataset / "manifest.json"
    if not manifest.exists():
        return False, f"no manifest at {manifest}"
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    validation = payload.get("validation") or {}
    if not validation.get("valid"):
        return False, f"validation.valid is not true: {validation.get('errors')}"
    return True, (
        f"{payload.get('dataset_id')} composite={payload.get('composite_sha256')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path,
        default=ROOT / "scaffold/experiments/rq5_longitudinal_40_v2",
    )
    parser.add_argument("--api-profile", default="api_02_rq5_session")
    parser.add_argument("--fallback-api-profile", action="append", default=[])
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--run-id-prefix", default="rq5v2_attrition_repair")
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--execute", action="store_true",
        help="actually run; without it the child runner only preflights",
    )
    args = parser.parse_args()

    ok, detail = dataset_is_valid(args.dataset)
    if not ok:
        raise SystemExit(f"dataset invalid: {detail}")
    print(f"dataset ok: {detail}", flush=True)

    by_arm: dict[str, list[str]] = {}
    for arm, sid in ATTRITED:
        by_arm.setdefault(arm, []).append(sid)

    if args.dry_run:
        print(f"\ndry run: {len(ATTRITED)} episodes across {len(by_arm)} arms")
        for arm, sids in sorted(by_arm.items()):
            print(f"  {arm:24s} {', '.join(sids)}")
        return 0

    failures = []
    for arm, sids in sorted(by_arm.items()):
        run_id = f"{args.run_id_prefix}_{arm}"
        command = [
            sys.executable, "-m", "scaffold.runners.run_rq5_longitudinal_real",
            str(args.dataset),
            "--run-id", run_id,
            "--arm", arm,
            "--trials", "1",
            "--api-profile", args.api_profile,
            "--max-concurrency", "1",
            "--max-attempts", str(args.max_attempts),


            "--retry-response-contract",
        ]
        for sid in sids:
            command += ["--sequence-id", sid]
        for profile in args.fallback_api_profile:
            command += ["--fallback-api-profile", profile]
        if args.output_root:
            command += ["--output-root", str(args.output_root)]
        if args.execute:
            command.append("--execute")

        print("=" * 78, flush=True)
        print(f"ARM {arm}: {len(sids)} sequence(s) -> run_id={run_id}", flush=True)
        print("=" * 78, flush=True)
        completed = subprocess.run(command, cwd=str(ROOT))
        if completed.returncode != 0:
            failures.append((arm, completed.returncode))
            print(f"  FAILED rc={completed.returncode}", file=sys.stderr, flush=True)

    if failures:
        print(f"\n{len(failures)} arm(s) failed: {failures}", file=sys.stderr)
        return 1
    print("\nattrition repair complete.")
    print("Next: re-run build_rq5_paired_analysis to merge the repaired episodes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
