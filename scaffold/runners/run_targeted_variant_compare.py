from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from scaffold.runners import method_freeze, method_freeze_v1
from scaffold.runners.run_episode_real import _preflight, _write_atomic
from scaffold.statewise import config
from scaffold.statewise.agents import llm_client
from scaffold.statewise.evaluation import failure_taxonomy
from scaffold.statewise.experiments import experimental_conditions, targeted_variants
from scaffold.statewise.runtime import lightweight_runtime


PROJECT_DIR = Path(__file__).resolve().parents[2]
CASES_DIR = PROJECT_DIR / "scaffold" / "cases"
DEFAULT_CASES = (
    "case_diag_env_joint_state",
    "case_diag_fs_joint_state",
    "case_diag_git_joint_state",
)
DEFAULT_VARIANTS = ("v0", "hybrid", "progress")


def _select_api_profile(name):
    if not name:
        return None
    try:
        from scaffold.local import local_api_config
    except ImportError as exc:
        raise SystemExit("named API profiles require scaffold/local/local_api_config.py") from exc
    profile = local_api_config.API_PROFILES.get(name)
    if not profile:
        raise SystemExit(f"unknown API profile: {name}")
    config.OPENAI_BASE_URL = profile["base_url"]
    config.OPENAI_API_KEY = profile["api_key"]
    config.MODEL_NAME = profile["model_name"]
    config.HUMAN_SIMULATOR_BASE_URL = profile["base_url"]
    config.HUMAN_SIMULATOR_API_KEY = profile["api_key"]
    config.HUMAN_SIMULATOR_MODEL_NAME = profile["model_name"]


    override = profile.get("temperature")
    config.MODEL_TEMPERATURE_OVERRIDE = (
        float(override) if override is not None else None
    )
    return name


def _totals(calls):
    def total(field):
        values = [item.get(field) for item in calls if isinstance(item.get(field), int)]
        return sum(values) if values else 0
    return {
        "calls": len(calls),
        "input_tokens": total("prompt_tokens"),
        "output_tokens": total("completion_tokens"),
        "total_tokens": total("total_tokens"),
        "failures": sum(not bool(item.get("ok")) for item in calls),
        "latency_seconds": round(sum(float(item.get("latency_seconds") or 0) for item in calls), 4),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--variant", action="append", dest="variants")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--output-dir", default=str(PROJECT_DIR / "runs" / "targeted_variant_compare"))
    parser.add_argument("--api-profile")
    args = parser.parse_args()
    api_profile = _select_api_profile(args.api_profile)
    case_ids = tuple(args.case_ids or DEFAULT_CASES)
    variants = tuple(args.variants or DEFAULT_VARIANTS)
    if config.FAKE_API:
        raise SystemExit("STATECLARIFY_FAKE_API must be false")
    if args.trials < 1:
        raise SystemExit("--trials must be positive")
    for variant in variants:
        targeted_variants.method_name(variant)

    freeze = method_freeze.verify()
    if not freeze["valid"]:
        raise SystemExit("StateWise-v0 freeze mismatch")
    v1_freeze = method_freeze_v1.verify()
    if "combined" in variants and not v1_freeze["valid"]:
        raise SystemExit("StateWise-v1 freeze mismatch")
    preflight = _preflight()
    started = datetime.now(timezone.utc)
    destination = Path(args.output_dir) / f"targeted-variants-{started.strftime('%Y%m%dT%H%M%SZ')}.json"
    manifest = {
        "kind": "statewise_targeted_variant_compare",
        "complete": False,
        "started_at": started.isoformat(),
        "updated_at": started.isoformat(),
        "model": config.MODEL_NAME,
        "api_profile": api_profile,
        "base_method_freeze": freeze,
        "statewise_v1_freeze": v1_freeze,
        "preflight": preflight,
        "case_ids": list(case_ids),
        "variants": list(variants),
        "trials": args.trials,
        "shared_setups": [],
        "records": [],
        "measurement_errors": [],
    }
    _write_atomic(destination, manifest)
    if not preflight["ok"]:
        manifest["complete"] = True
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_atomic(destination, manifest)
        print(f"manifest={destination.resolve()}")
        return 2

    for trial in range(args.trials):
        ordered_variants = variants if trial % 2 == 0 else tuple(reversed(variants))
        for case_id in case_ids:
            print(f"[setup:start] case={case_id} trial={trial}", flush=True)
            case_path = CASES_DIR / f"{case_id}.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            llm_client.reset_call_metrics()
            setup_started = time.perf_counter()
            try:
                shared_proposal = experimental_conditions.build_initial_proposal(
                    case, "corrupted"
                )
                setup_error = None
            except Exception as exc:
                shared_proposal = None
                setup_error = {
                    "case_id": case_id,
                    "trial": trial,
                    "stage": "shared_setup",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                }
            setup_calls = llm_client.get_call_metrics()
            manifest["shared_setups"].append({
                "case_id": case_id,
                "trial": trial,
                "initial_proposal": shared_proposal,
                "api": _totals(setup_calls),
                "wall_seconds": round(time.perf_counter() - setup_started, 4),
                "error": setup_error,
            })
            if setup_error:
                manifest["measurement_errors"].append(setup_error)
            _write_atomic(destination, manifest)
            print(
                f"[setup:done] case={case_id} trial={trial} "
                f"calls={len(setup_calls)}",
                flush=True,
            )
            if setup_error:
                print(
                    f"[setup:error] case={case_id} trial={trial} "
                    f"type={setup_error['error_type']}",
                    flush=True,
                )
                continue
            for variant in ordered_variants:
                print(
                    f"[unit:start] case={case_id} trial={trial} variant={variant}",
                    flush=True,
                )
                llm_client.reset_call_metrics()
                record = {
                    "case_id": case_id,
                    "trial": trial,
                    "variant": variant,
                    "method_name": targeted_variants.method_name(variant),
                    "method_fingerprint": targeted_variants.method_fingerprint(variant),
                }
                unit_started = time.perf_counter()
                try:
                    with targeted_variants.use_variant(variant):
                        result = lightweight_runtime.run_executable_case(
                            str(case_path),
                            condition="corrupted",
                            initial_proposal=copy.deepcopy(shared_proposal),
                        )
                    calls = llm_client.get_call_metrics()
                    arm = failure_taxonomy.build_arm_record(
                        case,
                        "mitigated",
                        result,
                        method_version=record["method_name"],
                        method_fingerprint=record["method_fingerprint"],
                        api_call_metrics=calls,
                    )
                    record.update({
                        "api": _totals(calls),
                        "wall_seconds": round(time.perf_counter() - unit_started, 4),
                        "arm_record": arm,
                        "raw_result": result,
                    })
                    episode = arm["episode"]
                    print(
                        f"{case_id} variant={variant} status={episode['status']} "
                        f"task={episode['task_success']} safe={not episode['safety_violation']} "
                        f"labels={arm['failure_labels']} calls={record['api']['calls']}",
                        flush=True,
                    )
                except Exception as exc:
                    calls = llm_client.get_call_metrics()
                    record.update({
                        "api": _totals(calls),
                        "wall_seconds": round(time.perf_counter() - unit_started, 4),
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:500],
                    })
                    manifest["measurement_errors"].append({
                        "case_id": case_id,
                        "trial": trial,
                        "variant": variant,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:500],
                    })
                manifest["records"].append(record)
                manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
                _write_atomic(destination, manifest)

    manifest["complete"] = True
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["updated_at"] = manifest["finished_at"]
    _write_atomic(destination, manifest)
    print(f"manifest={destination.resolve()}")
    return 1 if manifest["measurement_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
