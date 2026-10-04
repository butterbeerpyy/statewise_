import unittest

from scaffold.runners.export_paper_xlsx import _flatten_episode


def _case(expected_stop: bool):
    oracle = {"safe_terminal_actions": ["stop"]} if expected_stop else {}
    return {
        "case_id": "measurement-case",
        "task": "test task",
        "execution": {"oracle": oracle},
        "difficulty": {},
    }


def _episode(summary):
    return {
        "status": "SUCCEEDED",
        "spec": {"case_id": "measurement-case", "condition": "statewise_v1"},
        "attempts": [{"status": "SUCCEEDED", "result": {"summary": summary}}],
    }


class ExportMeasurementTests(unittest.TestCase):
    def test_acceptable_safe_terminal_is_required_for_correct_stop(self):
        row = _flatten_episode(
            "run", {"status": "COMPLETE", "experiment_config": {}},
            _episode({"acceptable_safe_terminal": True, "safety_violation": False,
                      "task_success": False}), _case(True))
        self.assertTrue(row["correct_safe_stop"])
        self.assertTrue(row["behaviorally_correct"])

    def test_unnecessary_safe_abort_is_not_correct_stop(self):
        row = _flatten_episode(
            "run", {"status": "COMPLETE", "experiment_config": {}},
            _episode({"acceptable_safe_terminal": False, "safety_violation": False,
                      "task_success": False}), _case(True))
        self.assertFalse(row["correct_safe_stop"])
        self.assertFalse(row["behaviorally_correct"])

    def test_action_completion_requires_no_violation(self):
        row = _flatten_episode(
            "run", {"status": "COMPLETE", "experiment_config": {}},
            _episode({"acceptable_safe_terminal": False, "safety_violation": False,
                      "task_success": True}), _case(False))
        self.assertTrue(row["action_completed"])
        self.assertTrue(row["behaviorally_correct"])

    def test_violation_is_not_action_completion(self):
        row = _flatten_episode(
            "run", {"status": "COMPLETE", "experiment_config": {}},
            _episode({"acceptable_safe_terminal": True, "safety_violation": True,
                      "task_success": True}), _case(False))
        self.assertFalse(row["action_completed"])
        self.assertFalse(row["correct_safe_stop"])
        self.assertFalse(row["behaviorally_correct"])


if __name__ == "__main__":
    unittest.main()
