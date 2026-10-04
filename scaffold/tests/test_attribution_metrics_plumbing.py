import unittest

from scaffold.statewise.core import attribution, interceptor


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


def _candidate(memory_id, claim):
    return {"id": "S1", "claim": claim, "source": f"memory:{memory_id}", "confidence": "high"}


class MemoryIdPlumbingTests(unittest.TestCase):
    def setUp(self):
        self.state = {"M1": _entry("M1", "project_env", "base")}
        self.action = {
            "tool": "package_manager",
            "operation": "install",
            "arguments": {"package": "rich"},
            "target": "base",
        }
        self.candidates = [_candidate("M1", "project_env = base")]

    def _score(self):
        return attribution.score_candidates(
            self.candidates,
            self.state,
            self.action,
            "install the missing dependency",
            ["M1"],
            interceptor.classify(self.action),
        )

    def test_scored_memory_candidate_carries_memory_id(self):

        scored = self._score()
        self.assertTrue(scored, "expected at least one scored candidate")
        for item in scored:
            source = str(item.get("source") or "")
            if source.startswith("memory:"):
                self.assertEqual(
                    source.split(":", 1)[1],
                    item.get("memory_id"),
                    f"memory_id missing or wrong for {item.get('id')}",
                )

    def test_metrics_see_the_scored_candidate(self):

        scored = self._score()
        metrics = attribution.stage_metrics(scored, [{"memory_id": "M1"}])
        self.assertEqual(1, metrics["memory_candidate_count"])
        self.assertIn("M1", metrics["candidate"]["memory_ids"])
        self.assertEqual(1.0, metrics["candidate"]["recall"])

    def test_empty_candidate_set_cannot_coexist_with_prefilter_false_negatives(self):

        scored = self._score()
        metrics = attribution.stage_metrics(scored, [{"memory_id": "M1"}])
        if metrics["memory_candidate_count"] == 0:
            self.assertEqual(
                0,
                metrics["cheap_filter_false_negative_count"],
                "candidate set is empty yet the prefilter reports false negatives",
            )

    def test_v2_path_specifically_preserves_memory_id(self):

        from scaffold.statewise.experiments import attribution_two_tier

        with attribution_two_tier.use_variant("two_tier"):
            scored = self._score()
        v2_items = [item for item in scored if item.get("attributed_v2")]
        if not v2_items:
            self.skipTest("V2 path produced no attributed candidates for this input")
        for item in v2_items:
            self.assertEqual(
                "M1", item.get("memory_id"), "V2 path dropped memory_id"
            )


if __name__ == "__main__":
    unittest.main()
