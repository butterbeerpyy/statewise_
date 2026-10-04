from __future__ import annotations

from unittest import mock
import sys
import unittest

from scaffold.runners import run_real_parallel


class RunRealParallelSerialTests(unittest.TestCase):
    def test_run_serial_invokes_run_real_once(self):
        completed = mock.Mock(returncode=0)
        with mock.patch.object(
            run_real_parallel.subprocess, "run", return_value=completed
        ) as run, mock.patch.object(
            run_real_parallel.time, "time", side_effect=[10.0, 22.0]
        ):
            code = run_real_parallel.run_serial(
                ["case_a", "case_b"], trials=2, quiet=True
            )

        self.assertEqual(0, code)
        command = run.call_args.args[0]
        self.assertEqual(
            [sys.executable, "-m", "scaffold.runners.run_real"],
            command[:3],
        )
        self.assertIn("--trials", command)
        self.assertIn("2", command)
        self.assertEqual(2, command.count("--case"))
        self.assertIn("case_a", command)
        self.assertIn("case_b", command)
        self.assertIn("--quiet", command)

    def test_main_serial_filters_cases(self):
        with mock.patch.object(
            run_real_parallel, "get_all_case_ids", return_value=["case_a", "case_b"]
        ), mock.patch.object(
            run_real_parallel, "run_serial", return_value=0
        ) as run_serial, mock.patch.object(
            sys, "argv",
            [
                "run_real_parallel.py",
                "--serial",
                "--case",
                "case_b",
                "--trials",
                "3",
                "--quiet",
            ],
        ):
            with self.assertRaises(SystemExit) as raised:
                run_real_parallel.main()

        self.assertEqual(0, raised.exception.code)
        run_serial.assert_called_once_with(["case_b"], 3, True)


if __name__ == "__main__":
    unittest.main()
