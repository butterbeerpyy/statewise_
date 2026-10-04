import unittest

from scaffold.runners import method_freeze
from scaffold.statewise.core import attribution, interceptor
from scaffold.statewise.experiments import attribution_two_tier


def _entry(memory_id, key, value):
    return {
        "id": memory_id,
        "key": key,
        "value": value,
        "confidence": "high",
        "source": "tool_verified:probe",
        "scope": {"repository": "example/repo", "branch": "*", "workspace": "*"},
        "status": "active",
        "supersedes": [],
        "ttl_days": None,
        "evidence": None,
        "updated_at": "session-1",
    }


class FrozenBoundaryTests(unittest.TestCase):
    def test_frozen_attribution_has_no_module_level_variant_switch(self):

        self.assertFalse(
            hasattr(attribution, "USE_ATTRIBUTION_V2"),
            "frozen attribution.py must not carry a variant feature flag",
        )

    def test_two_tier_scorer_lives_outside_the_frozen_boundary(self):
        for relative in method_freeze.METHOD_FILES:
            self.assertNotIn(
                "two_tier",
                relative,
                "the two-tier variant must not be a frozen method file",
            )

    def test_frozen_weights_are_the_published_v0_values(self):
        self.assertEqual(
            {"provenance": 0.25, "grounding": 0.35, "counterfactual": 0.40},
            attribution.ATTR_WEIGHTS,
        )
        self.assertEqual(0.30, attribution.CHEAP_FILTER_THRESHOLD)
        self.assertEqual(0.55, attribution.FINAL_ATTR_THRESHOLD)


class VariantContextTests(unittest.TestCase):
    def setUp(self):
        self.state = {"M1": _entry("M1", "project_env", "base")}
        self.action = {
            "tool": "package_manager",
            "operation": "install",
            "arguments": {"package": "rich"},
            "target": "base",
        }
        self.candidates = [{
            "id": "S1",
            "claim": "project_env = base",
            "source": "memory:M1",
            "confidence": "high",
            "grounder_declared": True,
        }]

    def _score(self):
        return attribution.score_candidates(
            self.candidates,
            self.state,
            self.action,
            "install the missing dependency",
            ["M1"],
            interceptor.classify(self.action),
        )

    def test_context_restores_the_frozen_scorer_and_weights(self):
        original = attribution.score_candidates
        with attribution_two_tier.use_variant("two_tier_reweighted"):
            self.assertIsNot(original, attribution.score_candidates)
            self.assertEqual(0.50, attribution.ATTR_WEIGHTS["grounding"])
        self.assertIs(original, attribution.score_candidates)
        self.assertEqual(0.35, attribution.ATTR_WEIGHTS["grounding"])
        self.assertEqual(0.30, attribution.CHEAP_FILTER_THRESHOLD)

    def test_freeze_stays_valid_while_the_variant_is_active(self):

        with attribution_two_tier.use_variant("two_tier"):
            inside = method_freeze.verify()["actual_fingerprint"]
        self.assertEqual(inside, method_freeze.verify()["actual_fingerprint"])

    def test_variant_output_keeps_every_frozen_contract_field(self):

        required = {
            "memory_id", "filter_reason", "relation", "p_prov", "p_ground",
            "cheap_score", "passed_cheap_filter", "attribution_policy",
            "provenance_link", "grounding_link", "provenance_basis",
            "grounding_basis",
        }
        with attribution_two_tier.use_variant("two_tier"):
            scored = self._score()
        self.assertTrue(scored)
        for item in scored:
            self.assertLessEqual(
                required,
                set(item),
                f"variant dropped {sorted(required - set(item))}",
            )

    def test_variant_candidates_reach_the_metrics_layer(self):
        with attribution_two_tier.use_variant("two_tier"):
            scored = self._score()
        metrics = attribution.stage_metrics(scored, [{"memory_id": "M1"}])
        self.assertEqual(1, metrics["memory_candidate_count"])
        self.assertIn("M1", metrics["candidate"]["memory_ids"])

    def test_variant_respects_the_counterfactual_candidate_budget(self):

        state = {
            f"M{index}": _entry(f"M{index}", f"project_env_{index}", "base")
            for index in range(1, 7)
        }
        candidates = [
            {
                "id": f"S{index}",
                "claim": f"project_env_{index} = base",
                "source": f"memory:M{index}",
                "confidence": "high",
                "grounder_declared": True,
            }
            for index in range(1, 7)
        ]
        with attribution_two_tier.use_variant("two_tier"):
            scored = attribution.score_candidates(
                candidates,
                state,
                self.action,
                "install the missing dependency",
                [f"M{index}" for index in range(1, 7)],
                interceptor.classify(self.action),
            )
        passed = [item for item in scored if item.get("passed_cheap_filter")]
        self.assertLessEqual(len(passed), attribution.MAX_CF_CANDIDATES)

    def test_unknown_variant_is_rejected(self):
        with self.assertRaises(ValueError):
            with attribution_two_tier.use_variant("does-not-exist"):
                pass
        self.assertEqual(0.35, attribution.ATTR_WEIGHTS["grounding"])


if __name__ == "__main__":
    unittest.main()
