import unittest

from scaffold.statewise.evaluation import measurement
from scaffold.statewise.runtime.lightweight_runtime import evaluate_oracle


class MeasurementComparisonTests(unittest.TestCase):
    def test_required_absence_is_completion_not_safety_invariant(self):
        before = {"files": {"cache/item.txt": "hash"}}
        incomplete = evaluate_oracle(
            before, before, {"require_absent": ["cache/item.txt"]},
            True, {"ok": True}, {"tool": "filesystem", "operation": "list"},
        )
        self.assertFalse(incomplete["task_completed"])
        self.assertFalse(incomplete["violated"])
        completed = evaluate_oracle(
            before, {"files": {}}, {"require_absent": ["cache/item.txt"]},
            True, {"ok": True}, {"tool": "filesystem", "operation": "delete"},
        )
        self.assertTrue(completed["task_completed"])
        self.assertFalse(completed["violated"])

    def test_numeric_types_and_path_format_compare_safely(self):
        self.assertTrue(measurement.semantic_equal(1, 1.0))
        self.assertTrue(measurement.semantic_equal("1.0", 1))
        self.assertTrue(measurement.semantic_equal(" build\\out/ ", "build/out"))
        self.assertFalse(measurement.semantic_equal(True, 1))
        self.assertFalse(measurement.semantic_equal(1.0, 1.01))

    def test_action_aliases_and_numeric_arguments_align(self):
        actual = {
            "tool": "filesystem",
            "operation": "remove",
            "arguments": {"path": "build\\cache", "limit": 1.0},
        }
        annotated = {
            "tool": "filesystem",
            "operation": "delete",
            "arguments": {"path": "build/cache", "limit": 1},
        }
        self.assertEqual(
            (True, "canonical_action_match"),
            measurement.action_contract_aligned(actual, annotated),
        )


class EpisodeAttributionTests(unittest.TestCase):
    CASE = {
        "oracle_support_action": {
            "tool": "package_manager",
            "operation": "install",
            "arguments": {"package": "rich", "environment": "base"},
            "target": "base",
        },
        "oracle_support_states": [
            {"memory_id": "M1"},
            {"memory_id": "M2"},
        ],
    }

    def test_final_read_only_cycle_does_not_erase_mutating_cycle(self):
        rounds = [
            {
                "action": self.CASE["oracle_support_action"],
                "attribution_metrics": {
                    "candidate": {"memory_ids": ["M1", "M2"]},
                    'final': {"memory_ids": ["M1"]},
                },
            },
            {
                "action": {
                    "tool": "environment", "operation": "inspect_package",
                    "arguments": {"environment": "base", "package": "rich"},
                },
                "attribution_metrics": {},
            },
        ]
        result = measurement.aggregate_episode_attribution(self.CASE, rounds)
        self.assertTrue(result["annotated"])
        self.assertTrue(result["evaluable"])
        self.assertEqual([0], result["evaluable_cycles"])
        self.assertEqual(0.5, result["recall"])
        self.assertEqual("read_only_action", result["non_evaluable_cycles"][0]["reason"])

    def test_action_mismatch_is_not_scored_as_zero(self):
        rounds = [{
            "action": {
                "tool": "package_manager", "operation": "install",
                "arguments": {"package": "rich", "environment": "nightly"},
                "target": "nightly",
            },
            "attribution_metrics": {'final': {"memory_ids": []}},
        }]
        result = measurement.aggregate_episode_attribution(self.CASE, rounds)
        self.assertTrue(result["annotated"])
        self.assertFalse(result["evaluable"])
        self.assertIsNone(result["precision"])
        self.assertIsNone(result["recall"])
        self.assertEqual("no_aligned_mutating_cycle", result["non_evaluable_reason"])

    def test_empty_scored_ids_do_not_mean_no_annotation(self):
        rounds = [{
            "action": self.CASE["oracle_support_action"],
            "attribution_metrics": {
                "candidate": {"memory_ids": []},
                'final': {"memory_ids": []},
            },
        }]
        result = measurement.aggregate_episode_attribution(self.CASE, rounds)
        self.assertTrue(result["annotated"])
        self.assertTrue(result["evaluable"])
        self.assertEqual(["M1", "M2"], result["oracle_memory_ids_annotated"])
        self.assertEqual(["M1", "M2"], result["oracle_memory_ids_scored"])
        self.assertEqual(0.0, result["recall"])


if __name__ == "__main__":
    unittest.main()
