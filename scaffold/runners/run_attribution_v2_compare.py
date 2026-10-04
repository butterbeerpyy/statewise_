from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import time

from scaffold.runners import method_freeze_v1
from scaffold.runners.run_episode_real import _preflight, _write_atomic
from scaffold.runners.run_targeted_variant_compare import _select_api_profile
from scaffold.statewise import config
from scaffold.statewise.agents import llm_client
from scaffold.statewise.experiments import attribution_v2, pilot_conditions
from scaffold.statewise.memory import memory_store


ROOT = Path(__file__).resolve().parents[2]
CASES_ROOT = ROOT / "scaffold" / "cases"
DEFAULT_CASES = (
    "case_diag_env_incomplete_trace",
    "case_diag_fs_semantic_decoy",
    "case_diag_git_semantic_decoy",
    "case_env2_fastapi_implicit",
    "case_fs2_petclinic_site_reports",
    "case_git2_rich_docs_target",
    "case_hard_env_release_matrix",
    "case_hard_git_multistate_release",
)
DEFAULT_VARIANTS = ("v1", "semantic_recall")
PROPOSAL_MODES = ("planner_episode", "annotated_action")


def _fingerprint(value):
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _totals(metrics):
    return {
        "calls": len(metrics),
        "failed_calls": sum(item.get("ok") is False for item in metrics),
        "prompt_tokens": sum(int(item.get("prompt_tokens") or 0) for item in metrics),
        "completion_tokens": sum(
            int(item.get("completion_tokens") or 0) for item in metrics
        ),
        "total_tokens": sum(int(item.get("total_tokens") or 0) for item in metrics),
        "latency_seconds": round(
            sum(float(item.get("elapsed_seconds") or 0) for item in metrics), 4
        ),
    }


def _build_shared_proposal(case, mode):

    if mode == "planner_episode":
        return pilot_conditions.build_proposal(case, "corrupted")
    action = case.get("oracle_support_action")
    if action is None:
        action = (case.get("safety") or {}).get("unsafe_action")
    if action is None:
        raise ValueError(
            f"{case.get('case_id')} has no annotated action contract"
        )
    state = pilot_conditions._condition_state(case, "corrupted")
    scope = (case.get("environment") or {}).get("scope")
    return {
        "action": copy.deepcopy(action),
        "rationale": (
            "Controlled decision-level evaluation of the supplied action "
            "against the Planner-visible persistent state."
        ),
        "planner_context_memory_ids": sorted(
            memory_store.active_entries(state, scope=scope)
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--variant", action="append", dest="variants")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--api-profile", default="api_03_gpt55")
    parser.add_argument(
        "--proposal-mode",
        choices=PROPOSAL_MODES,
        default="planner_episode",
        help=(
            "planner_episode measures a live initial decision; annotated_action "
            "is a controlled decision-level Attribution component test"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "runs" / "attribution_v2_compare"),
    )
    parser.add_argument("--run-id")
    args = parser.parse_args()
    if args.trials < 1:
        raise SystemExit("--trials must be positive")
    cases = tuple(args.case_ids or DEFAULT_CASES)
    variants = tuple(args.variants or DEFAULT_VARIANTS)
    for variant in variants:
        attribution_v2.method_name(variant)

    freeze = method_freeze_v1.verify()
    if not freeze["valid"]:
        raise SystemExit("StateWise-v1 freeze mismatch")
    _select_api_profile(args.api_profile)
    config.FAKE_API = False
    preflight = _preflight()
    if not preflight.get("ok"):
        raise SystemExit("API preflight failed")

    started = datetime.now(timezone.utc)
    run_id = args.run_id or started.strftime("attribution-v2-%Y%m%dT%H%M%SZ")
    destination = Path(args.output_dir).resolve() / f"{run_id}.json"
    if destination.exists():
        raise SystemExit(f"run already exists: {destination}")
    manifest = {
        "schema_version": "statewise-attribution-v2-compare-v1",
        "run_id": run_id,
        "status": "RUNNING",
        "started_at": started.isoformat(),
        "updated_at": started.isoformat(),
        "api_profile": args.api_profile,
        "model": config.MODEL_NAME,
        "proposal_mode": args.proposal_mode,
        "preflight": preflight,
        "statewise_v1_freeze": freeze,
        "variants": [
            {
                "name": variant,
                "method_name": attribution_v2.method_name(variant),
                "fingerprint": attribution_v2.method_fingerprint(variant),
            }
            for variant in variants
        ],
        "cases": list(cases),
        "trials": args.trials,
        "records": [],
        "errors": [],
    }
    _write_atomic(destination, manifest)

    for trial in range(args.trials):
        order = variants if trial % 2 == 0 else tuple(reversed(variants))
        for case_id in cases:
            path = CASES_ROOT / f"{case_id}.json"
            case = json.loads(path.read_text(encoding="utf-8"))
            llm_client.reset_call_metrics()
            shared_proposal = _build_shared_proposal(case, args.proposal_mode)
            setup_metrics = llm_client.get_call_metrics()
            proposal_fingerprint = _fingerprint(shared_proposal)
            for variant in order:
                record = {
                    "case_id": case_id,
                    "trial": trial,
                    "variant": variant,
                    "method_name": attribution_v2.method_name(variant),
                    "method_fingerprint": attribution_v2.method_fingerprint(variant),
                    "shared_initial_proposal": copy.deepcopy(shared_proposal),
                    "shared_initial_proposal_fingerprint": proposal_fingerprint,
                    "shared_setup_api": _totals(setup_metrics),
                }
                llm_client.reset_call_metrics()
                unit_started = time.perf_counter()
                try:
                    with tempfile.TemporaryDirectory(
                        prefix=f"attr-v2-{case_id[:24]}-",
                        dir=str(Path(args.output_dir).resolve()),
                    ) as episode_root:
                        with attribution_v2.use_variant(variant):
                            result = pilot_conditions.run_executable_arm(
                                str(path),
                                "statewise_v1",
                                episode_root=episode_root,
                                initial_proposal=copy.deepcopy(shared_proposal),
                            )
                    metrics = llm_client.get_call_metrics()
                    record.update({
                        "status": "SUCCEEDED",
                        "wall_seconds": round(time.perf_counter() - unit_started, 4),
                        "api": _totals(metrics),
                        "summary": pilot_conditions.summarize_result(
                            case, "statewise_v1", result
                        ),
                        "raw_result": result,
                    })
                except Exception as exc:
                    metrics = llm_client.get_call_metrics()
                    record.update({
                        "status": "FAILED",
                        "wall_seconds": round(time.perf_counter() - unit_started, 4),
                        "api": _totals(metrics),
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:500],
                    })
                    manifest["errors"].append({
                        "case_id": case_id,
                        "trial": trial,
                        "variant": variant,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:500],
                    })
                manifest["records"].append(record)
                manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
                _write_atomic(destination, manifest)
                summary = record.get("summary", {})
                print(
                    f"{case_id} variant={variant} status={record['status']} "
                    f"task={summary.get('task_success')} "
                    f"attrP={summary.get('attribution_precision')} "
                    f"attrR={summary.get('attribution_recall')} "
                    f"calls={record.get('api', {}).get('calls')}",
                    flush=True,
                )

    manifest["status"] = "COMPLETE" if not manifest["errors"] else "COMPLETE_WITH_ERRORS"
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["updated_at"] = manifest["finished_at"]
    _write_atomic(destination, manifest)
    print(f"manifest={destination}")
    return 0 if not manifest["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
