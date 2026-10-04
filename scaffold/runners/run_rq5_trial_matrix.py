from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATRIX = ROOT / "scaffold/experiments/rq5_trial_matrix_v1.json"
DEFAULT_SCOPE = ROOT / "scaffold/experiments/rq5_analysis_scope_v1.json"


def primary_sequence_ids(scope_path: Path, dataset: Path) -> list[str]:

    scope = json.loads(scope_path.read_text(encoding="utf-8"))
    domains = scope["primary_analysis"]["domains"]
    per_domain = int(scope["primary_analysis"]["sequences_per_domain"])
    excluded = set(scope["excluded_from_primary"]["sequence_ids"])
    ids = []
    for domain in domains:
        for index in range(1, per_domain + 1):
            sid = f"seq_{domain}_{index:03d}"
            if sid in excluded:
                continue
            if not (dataset / f"{sid}.json").exists():
                raise SystemExit(f"missing sequence file for {sid} in {dataset}")
            ids.append(sid)
    return ids


def build_units(matrix: dict, sequence_ids: list[str]) -> list[dict]:

    units = []
    plan = matrix["trial_plan"]
    for arm in plan["arms_at_3_trials"]:
        for trial_index in plan["trial_indices_to_add"]:
            units.append({
                "kind": "trials",
                "run_id": f"rq5v2_trial{trial_index}_{arm}",
                "arm": arm,
                "api_profile": None,
                "sequence_ids": sequence_ids,
                "label": f"trial {trial_index} / {arm}",
            })
    cross = matrix["cross_model_plan"]
    for entry in cross["models"]:
        for arm in cross["arms"]:
            slug = entry["model"].replace(".", "").replace("-", "_")
            units.append({
                "kind": "crossmodel",
                "run_id": f"rq5v2_base_{arm}_{slug}",
                "arm": arm,
                "api_profile": entry["api_profile"],
                "sequence_ids": sequence_ids,
                "label": f"{entry['model']} / {arm}",
            })
    return units


def already_done(run_dir: Path, expected: int) -> bool:

    summary = run_dir / "longitudinal_summary.json"
    if not summary.exists():
        return False
    try:
        payload = json.loads(summary.read_text(encoding="utf-8"))
    except Exception:
        return False
    graded = {
        row.get("sequence_id")
        for row in payload.get("sequence_arm_results") or []
    }
    return len(graded) >= expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--scope", type=Path, default=DEFAULT_SCOPE)
    parser.add_argument(
        "--dataset", type=Path,
        default=ROOT / "scaffold/experiments/rq5_longitudinal_40_v2",
    )
    parser.add_argument("--default-api-profile", default="api_02_rq5_session")
    parser.add_argument("--fallback-api-profile", action="append",
                        default=['api_02'])
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--only", choices=("trials", "crossmodel"), default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    if matrix.get("status") != "PRE_REGISTERED":
        raise SystemExit(f"matrix status is {matrix.get('status')!r}, refusing to run")
    print(f"matrix: {matrix['matrix_id']} ({matrix['status']})", flush=True)

    sequence_ids = primary_sequence_ids(args.scope, args.dataset)
    print(f"primary sequences: {len(sequence_ids)}", flush=True)

    units = build_units(matrix, sequence_ids)
    if args.only:
        units = [u for u in units if u["kind"] == args.only]

    planned_episodes = len(units) * len(sequence_ids)
    print(f"units: {len(units)}  episodes: {planned_episodes}", flush=True)

    if args.dry_run or not args.execute:
        print("\ndry run - units that would execute:")
        for u in units:
            print(f"  [{u['kind']:10s}] {u['run_id']:52s} "
                  f"arm={u['arm']:22s} profile={u['api_profile'] or 'default'}")
        print(f"\ntotal episodes: {planned_episodes}")
        print(f"declared api-call estimate: "
              f"{matrix['planned_volume']['total_api_calls_estimate']}")
        return 0

    output_root = args.output_root or (ROOT / "runs" / "rq5_longitudinal")
    started = time.time()
    completed, skipped, failed = [], [], []

    for i, unit in enumerate(units, 1):
        run_dir = output_root / unit["run_id"]
        if already_done(run_dir, len(unit["sequence_ids"])):
            print(f"[{i}/{len(units)}] SKIP (already complete) {unit['run_id']}",
                  flush=True)
            skipped.append(unit["run_id"])
            continue

        command = [
            sys.executable, "-m", "scaffold.runners.run_rq5_longitudinal_real",
            str(args.dataset),
            "--run-id", unit["run_id"],
            "--arm", unit["arm"],
            "--trials", "1",
            "--api-profile", unit["api_profile"] or args.default_api_profile,
            "--max-concurrency", "1",
            "--max-attempts", str(args.max_attempts),
            "--execute",
        ]
        for sid in unit["sequence_ids"]:
            command += ["--sequence-id", sid]

        if unit["kind"] != "crossmodel":
            for profile in args.fallback_api_profile:
                command += ["--fallback-api-profile", profile]
        if args.output_root:
            command += ["--output-root", str(args.output_root)]

        elapsed = (time.time() - started) / 60.0
        print("=" * 78, flush=True)
        print(f"[{i}/{len(units)}] {unit['label']}  ({elapsed:.0f} min elapsed)",
              flush=True)
        print(f"  run_id={unit['run_id']}", flush=True)
        print("=" * 78, flush=True)
        result = subprocess.run(command, cwd=str(ROOT))
        if result.returncode == 0:
            completed.append(unit["run_id"])
        else:
            failed.append((unit["run_id"], result.returncode))
            print(f"  FAILED rc={result.returncode} (continuing)",
                  file=sys.stderr, flush=True)

    total = (time.time() - started) / 60.0
    print("\n" + "=" * 78)
    print(f"matrix finished in {total:.0f} min")
    print(f"  completed: {len(completed)}")
    print(f"  skipped  : {len(skipped)}")
    print(f"  failed   : {len(failed)}")
    for run_id, rc in failed:
        print(f"     {run_id} rc={rc}")
    print("\nNext: re-run build_rq5_paired_analysis to merge.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
