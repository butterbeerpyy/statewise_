from __future__ import annotations

import unittest

from scaffold.runners import (
    analyze_attribution_v2_compare,
    method_freeze_v1,
    run_attribution_v2_compare,
)
from scaffold.statewise.experiments import attribution_v2


def _entry(memory_id, key, value, rank=1):
    return {
        "id": memory_id,
        "key": key,
        "value": value,
        "confidence": "low",
        "source": "agent_summary",
        "scope": {"repository": "example/repo"},
        "status": "active",
        "retrieval_rank": rank,
    }


class AttributionV2CandidateTests(unittest.TestCase):
    def test_filesystem_report_state_is_retrieved_without_oracle_labels(self):
        state = {
            "M1": _entry("M1", "site_reports_status", "stale Maven output"),
            "M2": _entry("M2", "database_role", "production", rank=2),
        }
        candidates = attribution_v2.augment_candidates(
            [],
            {
                "tool": "filesystem",
                "operation": "delete",
                "arguments": {"path": "target/site"},
            },
            state,
        )
        self.assertEqual(["memory:M1"], [item["source"] for item in candidates])
        self.assertEqual(
            "v2_semantic_action_retrieval",
            candidates[0]["candidate_origin"],
        )

    def test_pull_request_base_value_is_retrieved_from_visible_memory(self):
        state = {
            "M1": _entry("M1", "pr_target_branch", "release/13.x"),
        }
        candidates = attribution_v2.augment_candidates(
            [],
            {
                "tool": "git",
                "operation": "open_pull_request",
                "arguments": {
                    "branch": "docs/api-reference",
                    "base": "release/13.x",
                },
            },
            state,
        )
        self.assertEqual(["memory:M1"], [item["source"] for item in candidates])
        self.assertIn(
            "exact_memory_value_in_action",
            candidates[0]["candidate_retrieval_basis"],
        )

    def test_unrelated_shell_inspection_does_not_broadly_select_memory(self):
        state = {
            "M1": _entry("M1", "project_env", "gunicorn"),
            "M2": _entry("M2", "deployment_guide_version", "v3-gunicorn"),
        }
        candidates = attribution_v2.augment_candidates(
            [],
            {
                "tool": "shell",
                "operation": "execute",
                "arguments": {"command": "ps -eo pid,args"},
            },
            state,
        )
        self.assertEqual([], candidates)

    def test_variant_context_restores_frozen_v1_and_freeze_remains_valid(self):
        from scaffold.statewise.core import attribution, extract_states

        original = extract_states.extract
        original_grounding = attribution.grounding_signal
        with attribution_v2.use_variant("semantic_recall"):
            self.assertIsNot(original, extract_states.extract)
            self.assertIsNot(original_grounding, attribution.grounding_signal)
        self.assertIs(original, extract_states.extract)
        self.assertIs(original_grounding, attribution.grounding_signal)
        self.assertTrue(method_freeze_v1.verify()["valid"])

    def test_semantic_candidate_becomes_explicit_grounding_evidence(self):
        from scaffold.statewise.core import attribution

        candidate = attribution_v2.augment_candidates(
            [],
            {
                "tool": "filesystem",
                "operation": "delete",
                "arguments": {"path": "target/site"},
            },
            {"M1": _entry("M1", "site_reports_status", "stale Maven output")},
        )[0]
        with attribution_v2.use_variant("semantic_recall"):
            score, relation, _, basis = attribution.grounding_signal(
                candidate,
                _entry("M1", "site_reports_status", "stale Maven output"),
                {
                    "tool": "filesystem",
                    "operation": "delete",
                    "arguments": {"path": "target/site"},
                },
                {"mutation_types": ["filesystem_delete"]},
            )
        self.assertGreaterEqual(score, 0.30)
        self.assertEqual("action_necessity", relation)
        self.assertTrue(any(item.startswith("v2_semantic_action_link:") for item in basis))

    def test_retrieval_candidate_reaches_counterfactual_without_fake_grounding(self):
        from scaffold.statewise.core import attribution, interceptor

        state = {
            "M1": _entry(
                "M1",
                "site_reports_status",
                "current release audit report bundle",
            ),
        }
        action = {
            "tool": "filesystem",
            "operation": "delete",
            "arguments": {"path": "target/site"},
        }
        with attribution_v2.use_variant("retrieval"):
            candidates = attribution_v2.retrieve_candidates(
                [],
                action,
                state,
            )
            scored = attribution.score_candidates(
                candidates,
                state,
                action,
                "",
                ["M1"],
                {
                    **interceptor.classify(action),


                    "impact_score": 1,
                },
            )
        self.assertEqual(1, len(scored))
        self.assertEqual(0.0, scored[0]["p_ground"])
        self.assertTrue(scored[0]["passed_cheap_filter"])
        self.assertEqual(
            "v2_retrieval_counterfactual_budget",
            scored[0]["filter_reason"],
        )

    def test_graph_variant_adds_only_one_hop_explicit_neighbor(self):
        seed = _entry("M1", "site_reports_status", "stale report")
        seed["related_memory_ids"] = ["M2"]
        state = {
            "M1": seed,
            "M2": _entry("M2", "approval_owner", "release manager", rank=2),
            "M3": _entry("M3", "database_role", "production", rank=3),
        }
        candidates = attribution_v2.retrieve_candidates(
            [],
            {
                "tool": "filesystem",
                "operation": "delete",
                "arguments": {"path": "target/site"},
            },
            state,
            graph=True,
        )
        by_source = {item["source"]: item for item in candidates}
        self.assertIn("memory:M1", by_source)
        self.assertIn("memory:M2", by_source)
        self.assertNotIn("memory:M3", by_source)
        self.assertTrue(any(
            "graph_one_hop:M1:explicit_memory_edge" in basis
            for basis in by_source["memory:M2"]["candidate_retrieval_basis"]
        ))

    def test_retrieval_finalization_requires_stable_counterfactual(self):
        from scaffold.statewise.core import attribution

        candidate = {
            "id": "S1",
            "source": "memory:M1",
            "memory_id": "M1",
            "candidate_origin": "v2_decision_retrieval",
            "retrieval_rescue_candidate": True,
            "candidate_retrieval_score": 0.5,
            "provenance_link": True,
            "cheap_score": 0.1,
            "passed_cheap_filter": True,
        }
        unstable = {
            "memory_id": "M1",
            "action_changed": True,
            "delta_cf": 0.8,
            "counterfactual_stability": 0.25,
        }
        stable = {
            **unstable,
            "counterfactual_stability": 0.75,
        }
        with attribution_v2.use_variant("retrieval"):
            rejected = attribution.finalize([candidate], [unstable])[0]
            accepted = attribution.finalize([candidate], [stable])[0]
        self.assertFalse(rejected["critical"])
        self.assertTrue(accepted["critical"])
        self.assertEqual(
            "v2_robust_retrieval_counterfactual",
            accepted["critical_basis"],
        )

    def test_rescue_hard_filters_semantic_sibling_and_docs_namespace(self):
        filesystem_state = {
            "M1": _entry(
                "M1", "output_dir_status", "reproducible generated artifacts"
            ),
            "M2": _entry(
                "M2", "artifact_cache_status", "reproducible generated artifacts"
            ),
            "M3": _entry("M3", "retention_policy", "preserve signed bundles"),
        }
        filesystem_candidates = attribution_v2.retrieve_candidates(
            [{
                "id": "S1",
                "claim": "output_dir_status = reproducible generated artifacts",
                "source": "memory:M1",
                "grounder_declared": True,
            }],
            {
                "tool": "filesystem",
                "operation": "delete",
                "arguments": {"path": "artifact_bundle"},
            },
            filesystem_state,
        )
        filesystem_sources = {
            item["source"] for item in filesystem_candidates
        }
        self.assertIn("memory:M1", filesystem_sources)
        self.assertIn("memory:M3", filesystem_sources)
        self.assertNotIn("memory:M2", filesystem_sources)

        environment_state = {
            "M1": _entry("M1", "project_env", "base"),
            "M2": _entry("M2", "release_test_scope", "full"),
            "M3": _entry("M3", "docs_env", "base"),
        }
        environment_candidates = attribution_v2.retrieve_candidates(
            [{
                "id": "S1",
                "claim": "project_env = base",
                "source": "memory:M1",
                "grounder_declared": True,
            }],
            {
                "tool": "package_manager",
                "operation": "install",
                "arguments": {"package": "pytest"},
                "target": "base",
            },
            environment_state,
        )
        environment_sources = {
            item["source"] for item in environment_candidates
        }
        self.assertIn("memory:M1", environment_sources)
        self.assertIn("memory:M2", environment_sources)
        self.assertNotIn("memory:M3", environment_sources)

    def test_retrieval_does_not_run_when_v1_covers_required_facets(self):
        state = {
            "M1": _entry("M1", "project_env", "base"),
            "M2": _entry("M2", "release_test_scope", "full"),
            "M3": _entry("M3", "runtime_backend", "cuda"),
        }
        candidates = [
            {
                "id": "S1",
                "claim": "project_env = base",
                "source": "memory:M1",
                "grounder_declared": True,
            },
            {
                "id": "S2",
                "claim": "release_test_scope = full",
                "source": "memory:M2",
                "grounder_declared": True,
            },
        ]
        result = attribution_v2.retrieve_candidates(
            candidates,
            {
                "tool": "package_manager",
                "operation": "install",
                "arguments": {"package": "pytest"},
                "target": "base",
            },
            state,
        )
        self.assertEqual(candidates, result)

    def test_retrieval_preserves_status_token_and_supports_pr_target_state(self):
        filesystem = attribution_v2.retrieve_candidates(
            [],
            {
                "tool": "filesystem",
                "operation": "delete",
                "arguments": {"path": "htmlcov"},
            },
            {
                "M1": _entry("M1", "htmlcov_status", "generated coverage report"),
            },
        )
        self.assertEqual(["memory:M1"], [item["source"] for item in filesystem])
        self.assertIn("target_state", filesystem[0]["candidate_state_facets"])

        pull_request = attribution_v2.retrieve_candidates(
            [],
            {
                "tool": "git",
                "operation": "open_pull_request",
                "arguments": {
                    "branch": "docs/api-reference",
                    "base": "release/13.x",
                },
            },
            {
                "M1": _entry("M1", "pr_target_branch", "release/13.x"),
            },
        )
        self.assertEqual(["memory:M1"], [item["source"] for item in pull_request])
        self.assertIn(
            "target_selection", pull_request[0]["candidate_state_facets"]
        )

    def test_configured_placeholder_does_not_reject_environment_state(self):
        candidates = attribution_v2.retrieve_candidates(
            [],
            {
                "tool": "database",
                "operation": "migrate",
                "target": "configured",
                "arguments": {"migration": "head"},
            },
            {
                "M1": _entry("M1", "database_role", "staging"),
            },
        )
        self.assertEqual(["memory:M1"], [item["source"] for item in candidates])

    def test_exact_target_value_rescues_unseen_but_compatible_state_key(self):
        candidates = attribution_v2.retrieve_candidates(
            [],
            {
                "tool": "package_manager",
                "operation": "install",
                "arguments": {"package": "vite"},
                "target": "overwrite_immediately",
            },
            {
                "M1": _entry(
                    "M1", "build_output_policy", "overwrite immediately"
                ),
            },
        )
        self.assertEqual(["memory:M1"], [item["source"] for item in candidates])
        self.assertIn("target_binding", candidates[0]["candidate_state_facets"])
        self.assertEqual(0.0, candidates[0].get("p_ground", 0.0))

    def test_retrieval_context_restores_all_patched_functions(self):
        from scaffold.statewise.core import (
            attribution,
            critical_detect,
            extract_states,
        )

        originals = (
            extract_states.extract,
            attribution.grounding_signal,
            attribution.score_candidates,
            attribution.finalize,
            critical_detect._automatic_interventions,
        )
        with attribution_v2.use_variant("retrieval_graph"):
            self.assertIsNot(originals[0], extract_states.extract)
            self.assertIs(originals[1], attribution.grounding_signal)
            self.assertIsNot(originals[2], attribution.score_candidates)
            self.assertIsNot(originals[3], attribution.finalize)
        self.assertEqual(
            originals,
            (
                extract_states.extract,
                attribution.grounding_signal,
                attribution.score_candidates,
                attribution.finalize,
                critical_detect._automatic_interventions,
            ),
        )

    def test_retrieval_uses_three_stratified_counterfactual_interventions(self):
        def original(*_):
            return [
                {"kind": "remove", "value": None},
                {"kind": "mark_uncertain", "value": "old"},
                {"kind": "replace", "value": "candidate-a"},
                {"kind": "replace", "value": "candidate-b"},
                {"kind": "replace", "value": "candidate-c"},
            ]

        bounded = attribution_v2._retrieval_intervention_wrapper(original)
        self.assertEqual(
            [
                {"kind": "remove", "value": None},
                {"kind": "mark_uncertain", "value": "old"},
                {"kind": "replace", "value": "candidate-a"},
            ],
            bounded("claim", "old", "stage"),
        )

    def test_analysis_excludes_case_global_labels_for_a_different_action(self):
        def record(case_id, action):
            return {
                "case_id": case_id,
                "trial": 0,
                "variant": "retrieval",
                "status": "SUCCEEDED",
                "summary": {
                    "task_success": False,
                    "safety_violation": False,
                    "steps": 1,
                    "attribution_precision": 1.0,
                    "attribution_recall": 1.0,
                },
                "raw_result": {
                    "initial_action": action,
                    "attribution_metrics": {
                        "oracle_memory_ids": ["M1"],
                        "candidate": {"memory_ids": ["M1"]},
                        'final': {"memory_ids": ["M1"]},
                    },
                },
                "api": {},
            }

        aligned = record(
            "case_fs2_petclinic_site_reports",
            {
                "tool": "filesystem",
                "operation": "delete",
                "arguments": {"path": "target/site"},
            },
        )
        misaligned = record(
            "case_diag_fs_semantic_decoy",
            {
                "tool": "filesystem",
                "operation": "delete",
                "arguments": {"path": "artifact_cache"},
            },
        )
        analysis = analyze_attribution_v2_compare.analyze({
            "records": [aligned, misaligned],
        })
        row = analysis["table"][0]
        self.assertEqual(2, row["attribution_evaluable_episodes"])
        self.assertEqual(1, row["action_contract_aligned_episodes"])
        self.assertEqual(1, row["action_contract_misaligned_episodes"])
        self.assertEqual(1.0, row["aligned_final_micro_precision"])
        pairs = {
            item["case_id"]: item["variants"]["retrieval"]
            for item in analysis["paired_records"]
        }
        self.assertTrue(pairs["case_fs2_petclinic_site_reports"]["action_contract_aligned"])
        self.assertFalse(pairs["case_diag_fs_semantic_decoy"]["action_contract_aligned"])

    def test_controlled_proposal_contains_action_but_not_oracle_state_values(self):
        import json
        from pathlib import Path

        case = json.loads(
            (
                Path(run_attribution_v2_compare.CASES_ROOT)
                / "case_fs2_petclinic_site_reports.json"
            ).read_text(encoding="utf-8")
        )
        proposal = run_attribution_v2_compare._build_shared_proposal(
            case,
            "annotated_action",
        )
        self.assertEqual(case["safety"]["unsafe_action"], proposal["action"])
        self.assertNotIn(
            str(case["correct_state"]["value"]),
            proposal["rationale"],
        )
        self.assertNotIn("oracle_support_states", proposal)
        self.assertIn(case["memory_id"], proposal["planner_context_memory_ids"])


if __name__ == "__main__":
    unittest.main()
