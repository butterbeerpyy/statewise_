from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest import mock

from scaffold.statewise.agents import llm_client


class _Completions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def create(self, **request):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _client(outcomes):
    completions = _Completions(outcomes)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
        completions_fixture=completions,
    )


def _audit():
    return {
        "transport_attempts": 0,
        "connection_retry_count": 0,
        "availability_failure_count": 0,
        "availability_failure_types": [],
        "availability_wait_seconds": 0.0,
        "availability_wait_exhausted": False,
    }


class AvailabilityWaitTests(unittest.TestCase):
    def test_connection_and_server_failures_retry_inside_same_logical_call(self):
        connection_error = type("APIConnectionError", (Exception,), {})
        server_error = type("InternalServerError", (Exception,), {})
        response = object()
        client = _client([connection_error(), server_error(), response])
        audit = _audit()
        with mock.patch.object(
            llm_client.config, "API_CONNECTION_WAIT_TIMEOUT_SECONDS", 3600
        ), mock.patch.object(
            llm_client.config, "API_CONNECTION_RETRY_INTERVAL_SECONDS", 30
        ), mock.patch.object(llm_client.time, "sleep") as sleep:
            actual = llm_client._create_with_availability_wait(
                client, {"model": "test"}, audit
            )

        self.assertIs(response, actual)
        self.assertEqual(3, client.completions_fixture.calls)
        self.assertEqual(3, audit["transport_attempts"])
        self.assertEqual(2, audit["connection_retry_count"])
        self.assertEqual(2, audit["availability_failure_count"])
        self.assertEqual(60, audit["availability_wait_seconds"])
        self.assertEqual([mock.call(30), mock.call(30)], sleep.call_args_list)

    def test_auth_or_request_errors_fail_immediately(self):
        auth_error = type("AuthenticationError", (Exception,), {"status_code": 401})
        client = _client([auth_error()])
        audit = _audit()
        with mock.patch.object(
            llm_client.config, "API_CONNECTION_WAIT_TIMEOUT_SECONDS", 3600
        ), mock.patch.object(llm_client.time, "sleep") as sleep:
            with self.assertRaises(auth_error):
                llm_client._create_with_availability_wait(
                    client, {"model": "test"}, audit
                )

        self.assertEqual(1, audit["transport_attempts"])
        self.assertEqual(0, audit["connection_retry_count"])
        sleep.assert_not_called()

    def test_wait_exhausts_at_configured_upper_bound(self):
        connection_error = type("APIConnectionError", (Exception,), {})
        client = _client([connection_error()])
        audit = _audit()
        with mock.patch.object(
            llm_client.config, "API_CONNECTION_WAIT_TIMEOUT_SECONDS", 3600
        ), mock.patch.object(
            llm_client.config, "API_CONNECTION_RETRY_INTERVAL_SECONDS", 7200
        ), mock.patch.object(llm_client.time, "sleep") as sleep:
            with self.assertRaises(connection_error):
                llm_client._create_with_availability_wait(
                    client, {"model": "test"}, audit
                )

        self.assertAlmostEqual(3600, audit["availability_wait_seconds"], places=6)
        self.assertTrue(audit["availability_wait_exhausted"])
        self.assertEqual(0, audit["connection_retry_count"])
        sleep.assert_called_once()
        self.assertAlmostEqual(3600, sleep.call_args.args[0], places=6)


if __name__ == "__main__":
    unittest.main()
