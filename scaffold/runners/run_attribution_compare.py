from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone

from scaffold.statewise import config
from scaffold.statewise.agents import llm_client
from scaffold.statewise.core import attribution
from scaffold.statewise.experiments import experimental_conditions
from scaffold.statewise.runtime import lightweight_runtime


HERE = Path(__file__).resolve().parent
SCAFFOLD_DIR = HERE.parent
PROJECT_DIR = SCAFFOLD_DIR.parent
CASES_DIR = SCAFFOLD_DIR / "cases"
OUTPUT_DIR = PROJECT_DIR / "runs" / "attribution_compare"
LOCK_PATH = OUTPUT_DIR / ".active.lock"


def _pid_is_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _acquire_run_lock():

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            descriptor = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, str(os.getpid()).encode("ascii"))
            return descriptor
        except FileExistsError:
            try:
                owner_pid = int(LOCK_PATH.read_text(encoding="ascii").strip())
            except (OSError, ValueError):
                owner_pid = -1
            if _pid_is_alive(owner_pid):
                raise SystemExit(
                    f"Another attribution comparison is active (pid={owner_pid})."
                )
            LOCK_PATH.unlink(missing_ok=True)
    raise SystemExit("Could not acquire attribution comparison lock.")


def _release_run_lock(descriptor):
    os.close(descriptor)
    try:
        if LOCK_PATH.read_text(encoding="ascii").strip() == str(os.getpid()):
            LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def _sum_metric(calls, field):
    values = [item.get(field) for item in calls if isinstance(item.get(field), int)]
    return sum(values) if values else None


def _checkpoint(manifest, destination):

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_DIR / f".{destination.name}.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, destination)


def _preflight(label):

    llm_client.reset_call_metrics()
    started = time.perf_counter()
    response = llm_client.chat(
        stage=f"attribution_compare:{label}",
        messages=[{
            "role": "user",
            "content": 'Return only this JSON object: {"api_ready": true}',
        }],
    )
    calls = llm_client.get_call_metrics()
    return {
        "label": label,
        "ok": response.get("api_ready") is True,
        "wall_seconds": round(time.perf_counter() - started, 4),
        "calls": calls,
    }


def _summarize(policy, case_id, trial, mitigated, calls, elapsed, shared_setup):

    attribution_metrics = (
        mitigated.get("episode_attribution_metrics")
        or mitigated.get("attribution_metrics", {})
    )
    runtime = mitigated.get("runtime_execution", {})
    return {
        "policy": policy,
        "case_id": case_id,
        "trial": trial,
        "wall_seconds": round(elapsed, 4),
        "api_calls": len(calls),
        "successful_api_calls": sum(bool(item.get("ok")) for item in calls),
        "failed_api_calls": sum(not bool(item.get("ok")) for item in calls),
        "prompt_tokens": _sum_metric(calls, "prompt_tokens"),
        "completion_tokens": _sum_metric(calls, "completion_tokens"),
        "total_tokens": _sum_metric(calls, "total_tokens"),


        "shared_setup_wall_seconds": shared_setup["wall_seconds"],
        "shared_setup_api_calls": len(shared_setup["calls"]),
        "shared_setup_total_tokens": _sum_metric(shared_setup["calls"], "total_tokens"),
        "e2e_wall_seconds": round(elapsed + shared_setup["wall_seconds"], 4),
        "e2e_api_calls": len(calls) + len(shared_setup["calls"]),
        "e2e_total_tokens": (
            (_sum_metric(calls, "total_tokens") or 0)
            + (_sum_metric(shared_setup["calls"], "total_tokens") or 0)
        ),
        "candidate_recall": attribution_metrics.get("candidate", {}).get("recall"),
        "prefilter_recall": attribution_metrics.get("prefilter", {}).get("recall"),
        "final_recall": attribution_metrics.get('final', {}).get("recall"),
        "memory_candidates": attribution_metrics.get("memory_candidate_count"),
        "counterfactual_candidates": attribution_metrics.get("counterfactual_candidate_count"),
        "counterfactual_probes": attribution_metrics.get("counterfactual_probe_count"),
        "filter_false_negatives": attribution_metrics.get("cheap_filter_false_negative_count"),
        "routing_methods": [item.get("method") for item in mitigated.get("routing_decisions", [])],
        "replan_count": mitigated.get("replan_count"),
        "state_repaired": any(
            item.get("memory_update")
            for item in mitigated.get("human_interactions", [])
        ) or any(
            item.get("method") == "VERIFY_STATE"
            for item in mitigated.get("routing_decisions", [])
        ),
        "mitigated_task_completed": runtime.get("oracle", {}).get("task_completed"),
        "mitigated_safety_pass": runtime.get("oracle", {}).get("safety_pass"),
        "episode_status": runtime.get("episode_status"),
        "final_action": mitigated.get("final_action"),
    }


def _run_experiment():


    policies = ("weighted", "staged")
    case_ids = (
        "case_env_nightly",
        "case_output_dir",
        "case_git_force_push",
    )
    trials = 1
    paired_seed = 42

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = OUTPUT_DIR / f"compare-{run_id}.json"

    if config.FAKE_API:
        raise SystemExit("Set STATECLARIFY_FAKE_API=false: this runner is real-API only.")
    if not config.OPENAI_API_KEY:
        raise SystemExit("No API credential resolved for the main-agent role.")

    manifest = {
        "schema": "statewise.attribution-comparison.v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": config.MODEL_NAME,
        "human_simulator_model": config.HUMAN_SIMULATOR_MODEL_NAME,
        "base_url": config.OPENAI_BASE_URL,
        "temperature": config.MODEL_TEMPERATURE,
        "paired_seed": paired_seed,
        "api_timeout_seconds": {
            "connect": config.API_CONNECT_TIMEOUT_SECONDS,
            "read": config.API_READ_TIMEOUT_SECONDS,
            "write": config.API_WRITE_TIMEOUT_SECONDS,
            "pool": config.API_POOL_TIMEOUT_SECONDS,
        },
        "api_max_retries": config.API_MAX_RETRIES,
        "policies": list(policies),
        "case_ids": list(case_ids),
        "trials": trials,
        "status": "starting",
        "preflight": None,
        "shared_case_setup": [],
        "results": [],
    }
    original_seed = config.MODEL_SEED
    config.MODEL_SEED = paired_seed
    _checkpoint(manifest, destination)
    try:
        manifest["preflight"] = _preflight("initial")
        if not manifest["preflight"]["ok"]:
            raise RuntimeError("API preflight returned an invalid JSON readiness response")
        manifest["status"] = "running"
        _checkpoint(manifest, destination)
        print(
            f"preflight ok seconds={manifest['preflight']['wall_seconds']} "
            f"model={config.MODEL_NAME}",
            flush=True,
        )
        for trial in range(trials):


            ordered_policies = policies if trial % 2 == 0 else tuple(reversed(policies))
            for case_id in case_ids:
                case_path = CASES_DIR / f"{case_id}.json"
                case = lightweight_runtime.main_loop.load_case(str(case_path))
                llm_client.reset_call_metrics()
                setup_started = time.perf_counter()
                shared_initial_proposal = experimental_conditions.build_initial_proposal(
                    case, "corrupted"
                )
                shared_setup = {
                    "case_id": case_id,
                    "trial": trial,
                    "wall_seconds": round(time.perf_counter() - setup_started, 4),
                    "calls": llm_client.get_call_metrics(),
                    "initial_action": shared_initial_proposal.get("action"),
                }
                manifest["shared_case_setup"].append(shared_setup)
                _checkpoint(manifest, destination)
                for policy in ordered_policies:
                    llm_client.reset_call_metrics()
                    started = time.perf_counter()
                    record = None
                    full_evaluation = None
                    try:
                        with attribution.use_policy(policy):
                            full_evaluation = lightweight_runtime.run_executable_case(
                                str(case_path),
                                condition="corrupted",
                                initial_proposal=copy.deepcopy(shared_initial_proposal),
                            )
                        calls = llm_client.get_call_metrics()
                        record = _summarize(
                            policy,
                            case_id,
                            trial,
                            full_evaluation,
                            calls,
                            time.perf_counter() - started,
                            shared_setup,
                        )
                        record["api_call_metrics"] = calls
                        record["evaluation"] = full_evaluation
                    except Exception as exc:
                        calls = llm_client.get_call_metrics()
                        record = {
                            "policy": policy,
                            "case_id": case_id,
                            "trial": trial,
                            "wall_seconds": round(time.perf_counter() - started, 4),
                            "api_calls": len(calls),
                            "error_type": type(exc).__name__,
                            "error": str(exc)[:500],
                            "api_call_metrics": calls,
                        }


                        try:
                            record["recovery_preflight"] = _preflight(
                                f"recovery_after_{case_id}_{policy}"
                            )
                        except Exception as probe_exc:
                            record["recovery_preflight"] = {
                                "ok": False,
                                "error_type": type(probe_exc).__name__,
                                "error": str(probe_exc)[:500],
                                "calls": llm_client.get_call_metrics(),
                            }
                    manifest["results"].append(record)
                    _checkpoint(manifest, destination)
                    status = record.get("episode_status") or f"ERROR:{record.get('error_type')}"
                    print(
                        f"{case_id} policy={policy} status={status} "
                        f"calls={record.get('api_calls')} seconds={record.get('wall_seconds')} "
                        f"attr_recall={record.get('final_recall')} "
                        f"safe={record.get('mitigated_safety_pass')} "
                        f"completed={record.get('mitigated_task_completed')}",
                        flush=True,
                    )
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["fatal_error"] = {
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        }
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        _checkpoint(manifest, destination)
        raise
    except KeyboardInterrupt:
        manifest["status"] = "interrupted"
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        _checkpoint(manifest, destination)
        raise
    finally:
        config.MODEL_SEED = original_seed

    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["status"] = "completed"
    _checkpoint(manifest, destination)
    print(f"manifest={destination.resolve()}")


def main():
    lock_descriptor = _acquire_run_lock()
    try:
        _run_experiment()
    finally:
        _release_run_lock(lock_descriptor)


if __name__ == "__main__":
    main()
