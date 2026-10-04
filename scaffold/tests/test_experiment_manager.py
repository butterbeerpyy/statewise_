from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scaffold.runners import run_managed_pilot

from scaffold.statewise.experiments.experiment_manager import (
    EpisodeSpec,
    EpisodeStatus,
    ExperimentFailure,
    ExperimentManager,
    FailureKind,
    RetryPolicy,
    build_episodes_from_snapshot,
    canonical_fingerprint,
    verify_dataset_snapshot,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = PROJECT_ROOT / "scaffold" / "experiments" / "test_set_42_v1.json"
COMBINED_SNAPSHOT = (
    PROJECT_ROOT
    / "scaffold"
    / "experiments"
    / "regression_42_plus_batch2_54_v1.json"
)
CASES = PROJECT_ROOT / "scaffold" / "cases"


class DatasetSnapshotTests(unittest.TestCase):
    def test_frozen_42_case_snapshot_is_valid(self):
        result = verify_dataset_snapshot(SNAPSHOT, CASES)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(42, result["case_count"])

    def test_episode_builder_uses_snapshot_not_directory_scan(self):
        episodes = build_episodes_from_snapshot(SNAPSHOT, ["correct", "statewise_v1"], 2)
        self.assertEqual(42 * 2 * 2, len(episodes))
        self.assertEqual(len(episodes), len({item.episode_id for item in episodes}))

    def test_prior_42_plus_indexed_batch2_snapshot_is_valid(self):
        result = verify_dataset_snapshot(COMBINED_SNAPSHOT, CASES)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(54, result["case_count"])

    def test_named_profile_forces_live_mode(self):
        original = run_managed_pilot.config.FAKE_API
        try:
            run_managed_pilot.config.FAKE_API = True
            with mock.patch.object(run_managed_pilot, "_select_api_profile") as select:
                selected = run_managed_pilot._configure_api_profile('api_01')
            self.assertEqual('api_01', selected)
            select.assert_called_once_with('api_01')
            self.assertFalse(run_managed_pilot.config.FAKE_API)
        finally:
            run_managed_pilot.config.FAKE_API = original

    def test_preflight_selects_and_orders_first_healthy_fallback(self):
        with mock.patch.object(
            run_managed_pilot, "_configure_api_profile"
        ) as configure, mock.patch.object(
            run_managed_pilot,
            "_preflight",
            side_effect=[{"ok": False}, {"ok": True}],
        ):
            result, profiles = run_managed_pilot._preflight_profiles(
                ('api_01', 'api_02', 'api_03')
            )

        self.assertTrue(result["ok"])
        self.assertEqual('api_02', result["selected_profile"])
        self.assertEqual(('api_02', 'api_01', 'api_03'), profiles)
        self.assertEqual(
            [mock.call('api_01'), mock.call('api_02')],
            configure.call_args_list,
        )


class ExperimentManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.episodes = [
            EpisodeSpec("case-a--correct--trial-000", "case-a", "correct", 0),
            EpisodeSpec("case-b--correct--trial-000", "case-b", "correct", 0),
        ]

    def tearDown(self):
        self.temporary.cleanup()

    def manager(self, run_id="run-1", max_attempts=2):
        return ExperimentManager(
            self.root,
            run_id,
            {"model": "deepseek-v4-flash", "api_key": ""},
            self.episodes,
            max_concurrency=2,
            retry_policy=RetryPolicy(
                max_attempts=max_attempts,
                initial_backoff_seconds=0,
                max_backoff_seconds=0,
            ),
        )

    def test_success_uses_isolated_workspaces_and_redacts_manifest(self):
        seen = {}

        def worker(spec, context):
            seen[spec.episode_id] = context.workspace
            self.assertTrue(context.workspace.is_dir())
            return {
                "method_outcome": "STEP_LIMIT",
                "api_metrics": [{"ok": True, "total_tokens": 17}],
                "echo": "",
            }

        manifest = self.manager().run(worker)
        self.assertEqual("COMPLETE", manifest["status"])
        self.assertEqual(2, len(set(seen.values())))
        self.assertEqual(34, manifest["aggregate"]["usage"]["total_tokens"])
        raw = (self.root / "run-1" / "manifest.json").read_text(encoding="utf-8")
        self.assertNotIn("sk-test", raw)
        self.assertNotIn("sk-should", raw)
        self.assertIn("<redacted>", raw)
        self.assertEqual(
            {EpisodeStatus.SUCCEEDED.value: 2},
            manifest["aggregate"]["status_counts"],
        )

    def test_retryable_failure_is_checkpointed_then_retried(self):
        calls = {}

        def worker(spec, context):
            calls[spec.episode_id] = calls.get(spec.episode_id, 0) + 1
            if calls[spec.episode_id] == 1:
                raise TimeoutError("provider timed out")
            return {"ok": True}

        manifest = self.manager().run(worker)
        self.assertEqual("COMPLETE", manifest["status"])
        self.assertEqual(4, manifest["aggregate"]["attempts"])
        self.assertEqual(2, manifest["aggregate"]["failure_counts"][FailureKind.API_TIMEOUT.value])
        for state in manifest["episodes"].values():
            self.assertEqual(EpisodeStatus.SUCCEEDED.value, state["status"])
            self.assertEqual(2, len(state["attempts"]))

    def test_terminal_failure_is_not_retried(self):
        def worker(spec, context):
            raise ExperimentFailure(FailureKind.API_AUTH, "invalid API key")

        manifest = self.manager().run(worker)
        self.assertEqual("COMPLETE_WITH_FAILURES", manifest["status"])
        self.assertEqual(2, manifest["aggregate"]["attempts"])

    def test_resume_recovers_running_checkpoint(self):
        manager = self.manager(max_attempts=2)
        episode_id = self.episodes[0].episode_id
        manager._start_attempt(episode_id)
        resumed = self.manager(max_attempts=2)
        state = resumed._manifest["episodes"][episode_id]
        self.assertEqual(EpisodeStatus.PENDING.value, state["status"])
        self.assertEqual(FailureKind.INTERRUPTED.value, state["attempts"][0]["failure"]["kind"])
        manifest = resumed.run(lambda spec, context: {"resumed": True})
        self.assertEqual("COMPLETE", manifest["status"])
        self.assertEqual(3, manifest["aggregate"]["attempts"])

    def test_resume_rejects_config_change(self):
        self.manager()
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            ExperimentManager(
                self.root,
                "run-1",
                {"model": "different"},
                self.episodes,
            )

    def test_config_fingerprint_ignores_secret_value(self):
        left = canonical_fingerprint({"model": "m", "api_key": "sk-left-secret"})
        right = canonical_fingerprint({"model": "m", "api_key": "sk-right-secret"})
        self.assertEqual(left, right)

    def test_active_run_lock_prevents_double_scheduler(self):
        manager = self.manager()
        manager.lock_path.write_text(json.dumps({
            "run_id": manager.run_id,
            "pid": os.getpid(),
            "hostname": __import__("socket").gethostname(),
        }), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "already active"):
            manager.run(lambda spec, context: {"ok": True})

    def test_workspace_storage_name_is_short_stable_and_distinct(self):
        long_id = "case-with-a-very-long-name--generic_clarification--trial-000"
        first = ExperimentManager._episode_storage_name(long_id)
        second = ExperimentManager._episode_storage_name(long_id)
        other = ExperimentManager._episode_storage_name(long_id + "-other")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertLessEqual(len(first), 16)
