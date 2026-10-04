from __future__ import annotations

from collections import Counter
import unittest

from scaffold.runners import build_paper_benchmark_package as package


class PaperBenchmarkPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot, cls.entries, cls.cases, cls.metadata = package._load_cases(
            package.DEFAULT_SNAPSHOT
        )

    def test_dev_stress_selection_is_deterministic_and_balanced(self):
        first = package._select_dev_stress(self.metadata)
        second = package._select_dev_stress(self.metadata)
        self.assertEqual(
            [item["case_id"] for item in first],
            [item["case_id"] for item in second],
        )
        self.assertEqual(96, len(first))
        self.assertEqual(
            {"environment": 32, "filesystem": 32, "git": 32},
            dict(Counter(item["operational_domain"] for item in first)),
        )
        self.assertFalse(
            any(item["capability_score_eligible"] is False for item in first)
        )

    def test_heldout_spec_quotas_sum_and_do_not_relabel_current_pool(self):
        spec = package._heldout_spec()
        self.assertEqual(300, spec["target_case_count"])
        self.assertEqual(300, sum(spec["domain_quota"].values()))
        for quota in spec["within_each_60_case_domain"].values():
            self.assertEqual(60, sum(quota.values()))
        self.assertEqual(236, spec["new_blueprints_required"]["total"])
        self.assertEqual(
            64,
            spec["existing_unseen_blueprint_allocation"][
                "heldout_reserved_count"
            ],
        )
        self.assertIn(
            "all 224 cases in statewise_current_pool_v1",
            spec["contamination_boundary"]["excluded_from_heldout"],
        )
        frame = package._heldout_slots(spec)
        self.assertEqual(300, frame["slot_count"])
        self.assertEqual(
            300, len({slot["slot_id"] for slot in frame["slots"]})
        )
        for domain, domain_count in spec["domain_quota"].items():
            domain_slots = [
                slot
                for slot in frame["slots"]
                if slot["operational_domain"] == domain
            ]
            self.assertEqual(domain_count, len(domain_slots))
            for axis, expected in spec[
                "within_each_60_case_domain"
            ].items():
                self.assertEqual(
                    expected,
                    dict(Counter(slot[axis] for slot in domain_slots)),
                )

    def test_failure_regression_is_explicitly_development_only(self):
        manifest = {
            "run_id": "synthetic",
            "status": "COMPLETE",
        }
        del manifest
        entries = {
            "case_safety": {"file": "safety.json", "case_id": "case_safety"},
            "case_limit": {"file": "limit.json", "case_id": "case_limit"},
        }
        metadata = {
            case_id: {
                "operational_domain": "environment",
                "phase": "test",
                "quota_bucket": "test",
                "source_family": "test",
                "corruption_operator": "STALE_VALUE",
                "observability": "O2",
                "causal_depth": "D3",
                "impact": "I4",
                "repository": "example/repo",
            }
            for case_id in entries
        }
        records = {
            ("case_safety", "statewise_v2_retrieval"): {
                "summary": {
                    "safety_violation": True,
                    "status": "SAFETY_FAILURE",
                }
            },
            ("case_limit", "statewise_v2_retrieval"): {
                "summary": {
                    "safety_violation": False,
                    "status": "STEP_LIMIT",
                }
            },
        }
        selected = package._failure_regression_manifest(
            metadata, entries, records
        )
        self.assertEqual(2, selected["case_count"])
        self.assertEqual(
            "development_only_not_headline_not_heldout",
            selected["paper_use"],
        )
        rows = package._failure_rows(metadata, records)
        self.assertEqual(2, len(rows))
        self.assertEqual(
            {"state_action_safety_failure", "planning_non_convergence"},
            {row["primary_failure_family"] for row in rows},
        )


if __name__ == "__main__":
    unittest.main()
