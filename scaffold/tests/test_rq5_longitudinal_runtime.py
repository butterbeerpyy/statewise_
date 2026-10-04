from __future__ import annotations

import copy
import json
from pathlib import Path

from scaffold.statewise.evaluation.longitudinal_runtime import (
    initial_memory_for_arm,
    materialize_case,
    memory_contract,
    smoke_preflight,
)
from scaffold.statewise.agents.permission_simulator import CasePermissionSimulator
from scaffold.statewise.experiments import pilot_conditions
from scaffold.statewise.memory import memory_repair
from scaffold.statewise.runtime import lightweight_runtime


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "scaffold" / "experiments" / "rq5_longitudinal_20_v1"


def _sequence(name="seq_environment_001"):
    return json.loads((DATASET / f"{name}.json").read_text(encoding="utf-8"))


def test_arm_initial_memory_semantics_are_explicit():
    sequence = _sequence()
    assert initial_memory_for_arm(sequence, "no_memory") == {}
    assert initial_memory_for_arm(sequence, "correct")["RQ5_CORRECT"]["value"] == "nightly"
    assert initial_memory_for_arm(sequence, "statewise_v1")["RQ5_CORRUPTED"]["value"] == "base"
    assert initial_memory_for_arm(sequence, "bare_approval")["RQ5_CORRUPTED"]["value"] == "base"


def test_memory_contract_requires_scope_and_transitive_lineage():
    sequence = _sequence()
    state = initial_memory_for_arm(sequence, "statewise_v1")
    assert memory_contract(sequence, state)["repaired_contract_satisfied"] is False
    first = memory_repair.repair(
        state,
        key="project_env",
        value="nightly",
        source="human_simulator_confirmed",
        confidence="high",
        evidence={},
        scope=copy.deepcopy(sequence["shared_state"]["scope"]),
        supersede_id="RQ5_CORRUPTED",
    )
    second = memory_repair.repair(
        state,
        key="project_env",
        value="nightly",
        source="tool_verified:test",
        confidence="high",
        evidence={},
        scope=copy.deepcopy(sequence["shared_state"]["scope"]),
        supersede_id=first,
    )
    contract = memory_contract(sequence, state)
    assert contract["active_memory_id"] == second
    assert contract["lineage_matches"] is True
    assert contract["repaired_contract_satisfied"] is True
    state[second]["scope"] = {"repository": "another-repository"}
    assert memory_contract(sequence, state)["repaired_contract_satisfied"] is False


def test_oracle_repair_is_idempotent_after_valid_longitudinal_repair():
    sequence = _sequence()
    case = materialize_case(sequence, sequence["tasks"][0])
    state = initial_memory_for_arm(sequence, "oracle_statewise")
    repaired, first = pilot_conditions._repair_oracle_state(case, state)
    repaired_again, second = pilot_conditions._repair_oracle_state(case, repaired)
    assert len(first) == 1
    assert second == []
    assert repaired_again == repaired
    assert memory_contract(sequence, repaired_again)["repaired_contract_satisfied"] is True


def test_each_domain_has_an_executable_correct_action_contract():
    for sequence_id in (
        "seq_environment_001",
        "seq_filesystem_001",
        "seq_git_001",
        "seq_database_001",
        "seq_deployment_001",
    ):
        sequence = _sequence(sequence_id)
        case = materialize_case(sequence, sequence["tasks"][0])
        report = smoke_preflight(case)
        assert report["ok"] is True, (sequence_id, report)


def test_each_domain_wrong_state_action_has_observable_safety_violation():
    for sequence_id in (
        "seq_environment_001",
        "seq_filesystem_001",
        "seq_git_001",
        "seq_database_001",
        "seq_deployment_001",
    ):
        sequence = _sequence(sequence_id)
        case = materialize_case(sequence, sequence["tasks"][0])
        execution = case["execution"]
        action = case["safety"]["unsafe_action"]
        with lightweight_runtime.EpisodeSandbox(execution) as sandbox:
            before = sandbox.snapshot()
            result = sandbox.execute(action)
            after = sandbox.snapshot()
            oracle = lightweight_runtime.evaluate_oracle(
                before,
                after,
                execution["oracle"],
                action_executed=True,
                action_result=result,
                action=action,
            )
        assert oracle["violated"] is True, (sequence_id, oracle)
        assert oracle["present_forbidden_paths"], (sequence_id, oracle)


def test_materialized_permission_policy_allows_truth_and_denies_stale_action():
    for sequence_id in ("seq_database_001", "seq_deployment_001"):
        sequence = _sequence(sequence_id)
        case = materialize_case(sequence, sequence["tasks"][0])
        channel = CasePermissionSimulator(case)
        assert channel.answer({"action": case["execution"]["smoke_action"]})["allowed"] is True
        assert channel.answer({"action": case["safety"]["unsafe_action"]})["allowed"] is False


def test_summary_accepts_none_episode_attribution_metrics():
    sequence = _sequence()
    case = materialize_case(sequence, sequence["tasks"][0])
    state = initial_memory_for_arm(sequence, "statewise_v1")
    result = {
        "initial_memory": state,
        "final_memory": state,
        "episode_attribution_metrics": {"precision": None, "recall": None},
        "runtime_execution": {"oracle": {}, "trajectory": []},
        "residual_gate": {},
    }
    summary = pilot_conditions.summarize_result(case, "statewise_v1", result)
    assert summary["attribution_precision"] is None
    assert summary["attribution_recall"] is None
