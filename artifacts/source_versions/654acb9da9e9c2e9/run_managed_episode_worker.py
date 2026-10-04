from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys
import traceback


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scaffold.runners.run_targeted_variant_compare import _select_api_profile
from scaffold.statewise import config
from scaffold.statewise.agents import llm_client
from scaffold.statewise.evaluation import failure_diagnosis
from scaffold.statewise.experiments import pilot_conditions


def _write(path: Path, payload) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    profile = request.get("provider_profile")
    if profile and profile != "fake":
        _select_api_profile(profile)
        config.FAKE_API = False
    else:
        config.FAKE_API = True

    case_path = Path(request["case_path"]).resolve()
    case = json.loads(case_path.read_text(encoding="utf-8"))
    llm_client.reset_call_metrics()
    try:
        result = pilot_conditions.run_executable_arm(
            str(case_path),
            request["arm"],
            episode_root=request.get("episode_root"),
            initial_proposal=copy.deepcopy(request.get("initial_proposal")),
        )
        metrics = llm_client.get_call_metrics()


        foreign = failure_diagnosis.foreign_api_stages(case.get("case_id"), metrics)
        if foreign:
            _write(args.output, {
                "ok": False,
                "error_type": "EpisodeIsolationError",
                "error": (
                    f"{len(foreign)} foreign API stage(s) observed in an isolated "
                    f"worker; measurement is not attributable to "
                    f"{case.get('case_id')}: {foreign[:5]}"
                ),
                "api_metrics": metrics,
            })
            return 1
        summary = pilot_conditions.summarize_result(case, request["arm"], result)
        _write(args.output, {
            "ok": True,
            "summary": summary,
            "api_metrics": metrics,
            "raw_result": result,
        })
        return 0
    except Exception as exc:
        _write(args.output, {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc)[:2000],
            "traceback": traceback.format_exc(limit=20),
            "api_metrics": llm_client.get_call_metrics(),
        })
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
