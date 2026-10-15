"""Simulated transport tests for Jules adapter harness integration."""
import asyncio
import os
import unittest
from unittest.mock import MagicMock, patch

from swe_af.runtime.application_harness import (
    _REGISTERED_HANDLERS,
    HarnessRequest,
    register_backend,
)
from swe_af.runtime.jules_adapter import (
    JulesAdapter,
    JulesHarnessAgent,
    register_jules,
)


class TestJulesHarnessIntegration(unittest.TestCase):
    def setUp(self):
        self.old_key = os.environ.get("JULES_API_KEY")
        os.environ["JULES_API_KEY"] = "mock-harness-key"

    def tearDown(self):
        if self.old_key is not None:
            os.environ["JULES_API_KEY"] = self.old_key
        else:
            os.environ.pop("JULES_API_KEY", None)

    def test_registration_and_handler_selection(self):
        register_jules()
        self.assertIn("jules", _REGISTERED_HANDLERS)

    @patch("urllib.request.urlopen")
    def test_harness_agent_full_invocation_simulated(self, mock_urlopen):
        # Session creation response
        resp_session = MagicMock()
        resp_session.read.return_value = b'{"name": "sessions/sess-harness", "id": "sess-harness", "state": "QUEUED"}'

        # Status response
        resp_status = MagicMock()
        resp_status.read.return_value = b'{"name": "sessions/sess-harness", "state": "COMPLETED"}'

        # Activities/Result response
        resp_result = MagicMock()
        resp_result.read.return_value = b'{"activities": [{"id": "act-1"}]}'

        # Provide side_effect for sequential urlopen calls
        mock_urlopen.side_effect = [
            MagicMock(__enter__=MagicMock(return_value=resp_session), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_status), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_result), __exit__=MagicMock()),
        ]

        agent = JulesHarnessAgent()
        result = asyncio.run(agent.harness("Run harness task"))

        self.assertEqual(result.session_id, "sess-harness")
        self.assertEqual(result.status["state"], "COMPLETED")
        self.assertTrue(result.parsed["complete"])
        self.assertEqual(len(result.activities.get("activities", [])), 1)
        self.assertEqual(mock_urlopen.call_count, 3)

        # First call must be POST sessions
        first_call_req = mock_urlopen.call_args_list[0][0][0]
        self.assertEqual(first_call_req.get_method(), "POST")
        self.assertEqual(first_call_req.full_url, "https://jules.googleapis.com/v1alpha/sessions")
        self.assertEqual(first_call_req.headers.get("X-goog-api-key"), "mock-harness-key")

    @patch("urllib.request.urlopen")
    def test_harness_handler_registered_invoked_via_harness_request(self, mock_urlopen):
        resp_session = MagicMock()
        resp_session.read.return_value = b'{"name": "sessions/sess-1", "id": "sess-1"}'
        resp_status = MagicMock()
        resp_status.read.return_value = b'{"state": "COMPLETED"}'
        resp_result = MagicMock()
        resp_result.read.return_value = b'{"activities": []}'

        mock_urlopen.side_effect = [
            MagicMock(__enter__=MagicMock(return_value=resp_session), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_status), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_result), __exit__=MagicMock()),
        ]

        register_jules()
        handler = _REGISTERED_HANDLERS["jules"]
        req = HarnessRequest.create("Prompt test", {"require_plan_approval": True})

        dummy_agent = MagicMock()
        result = asyncio.run(handler(dummy_agent, req))

        self.assertEqual(result.session_id, "sess-1")
        self.assertTrue(result.parsed["complete"])
        self.assertEqual(mock_urlopen.call_count, 3)

    @patch("urllib.request.urlopen")
    def test_app_operational_flow_with_jules_backend(self, mock_urlopen):
        import swe_af.app
        from swe_af.runtime.application_harness import dispatch_harness

        resp_session = MagicMock()
        resp_session.read.return_value = b'{"name": "sessions/sess-prod", "id": "sess-prod"}'
        resp_status = MagicMock()
        resp_status.read.return_value = b'{"state": "COMPLETED"}'
        resp_result = MagicMock()
        resp_result.read.return_value = b'{"activities": [{"id": "act-init"}]}'

        mock_urlopen.side_effect = [
            MagicMock(__enter__=MagicMock(return_value=resp_session), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_status), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_result), __exit__=MagicMock()),
        ]

        old_backend = os.environ.get("SWE_HARNESS_BACKEND")
        os.environ["SWE_HARNESS_BACKEND"] = "jules"
        try:
            result = asyncio.run(
                dispatch_harness(
                    swe_af.app.app,
                    prompt="Operational task execution",
                    require_plan_approval=True,
                )
            )
            self.assertEqual(result.session_id, "sess-prod")
            self.assertEqual(result.status["state"], "COMPLETED")
            self.assertTrue(result.parsed["complete"])
            self.assertEqual(len(result.activities["activities"]), 1)
            self.assertEqual(mock_urlopen.call_count, 3)
        finally:
            if old_backend is not None:
                os.environ["SWE_HARNESS_BACKEND"] = old_backend
            else:
                os.environ.pop("SWE_HARNESS_BACKEND", None)

    @patch("urllib.request.urlopen")
    def test_harness_preserves_created_session_when_get_fails(self, mock_urlopen):
        import io, urllib.error
        from swe_af.runtime.application_harness import dispatch_harness
        import swe_af.app

        resp_session = MagicMock()
        resp_session.read.return_value = b'{"name": "sessions/sess-success", "id": "sess-success"}'

        err_body = io.BytesIO(b'{"error": {"code": 404, "message": "Activities not ready yet"}}')
        http_err = urllib.error.HTTPError(
            url="https://jules.googleapis.com/v1alpha/sessions/sess-success/activities",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=err_body,
        )

        mock_urlopen.side_effect = [
            MagicMock(__enter__=MagicMock(return_value=resp_session), __exit__=MagicMock()),
            http_err,  # get_status fails
        ]

        old_backend = os.environ.get("SWE_HARNESS_BACKEND")
        os.environ["SWE_HARNESS_BACKEND"] = "jules"
        try:
            result = asyncio.run(
                dispatch_harness(
                    swe_af.app.app,
                    prompt="Verify session preserved",
                    require_plan_approval=True,
                )
            )
            # Session is preserved despite GET errors
            self.assertEqual(result.session_id, "sess-success")
            self.assertTrue(result.status.get("unconfirmed"))
            self.assertIn("404", result.status.get("error", ""))
            self.assertTrue(result.activities.get("unconfirmed"))
            # Remote flow stopped immediately without calling activities endpoint
            self.assertEqual(mock_urlopen.call_count, 2)
            self.assertTrue(result.is_error)
            self.assertFalse(result.parsed["complete"])
        finally:
            if old_backend is not None:
                os.environ["SWE_HARNESS_BACKEND"] = old_backend
            else:
                os.environ.pop("SWE_HARNESS_BACKEND", None)


    @patch("urllib.request.urlopen")
    def test_audit_persists_session_id_before_get_calls(self, mock_urlopen):
        import tempfile, json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.jsonl"
            
            resp_session = MagicMock()
            resp_session.read.return_value = b'{"name": "sessions/sess-audit-1", "id": "sess-audit-1"}'
            resp_status = MagicMock()
            resp_status.read.return_value = b'{"state": "COMPLETED"}'
            resp_result = MagicMock()
            resp_result.read.return_value = b'{"activities": []}'

            call_order = []
            def fake_urlopen(req, *args, **kwargs):
                url = req.full_url
                if "/activities" in url:
                    call_order.append("GET_ACTIVITIES")
                    return MagicMock(__enter__=MagicMock(return_value=resp_result), __exit__=MagicMock())
                elif "sessions/" in url:
                    call_order.append("GET_STATUS")
                    return MagicMock(__enter__=MagicMock(return_value=resp_status), __exit__=MagicMock())
                else:
                    call_order.append("POST_CREATE")
                    # Check that audit log does NOT exist before POST completes
                    self.assertFalse(audit_file.exists())
                    return MagicMock(__enter__=MagicMock(return_value=resp_session), __exit__=MagicMock())

            mock_urlopen.side_effect = fake_urlopen

            agent = JulesHarnessAgent(audit_path=audit_file)
            res = asyncio.run(agent.harness("Audit sequence test prompt"))

            # Order must be creation -> persistence -> get calls
            self.assertEqual(call_order, ["POST_CREATE", "GET_STATUS", "GET_ACTIVITIES"])
            self.assertTrue(audit_file.exists())
            
            lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["session_id"], "sess-audit-1")
            self.assertEqual(record["outcome"], "created")
            # Ensure no credentials or prompt text leak in audit record
            self.assertNotIn("mock-harness-key", lines[0])
            self.assertNotIn("Audit sequence test prompt", lines[0])

    @patch("swe_af.runtime.jules_adapter._persist_session_audit")
    @patch("urllib.request.urlopen")
    def test_audit_failure_does_not_repeat_session_creation(self, mock_urlopen, mock_persist):
        mock_persist.side_effect = RuntimeError("Simulated audit disk write failure")

        resp_session = MagicMock()
        resp_session.read.return_value = b'{"name": "sessions/sess-fail-write", "id": "sess-fail-write"}'

        mock_urlopen.side_effect = [
            MagicMock(__enter__=MagicMock(return_value=resp_session), __exit__=MagicMock()),
        ]

        agent = JulesHarnessAgent()
        res = asyncio.run(agent.harness("Test audit failure isolation"))

        # Exactly 1 POST call made; zero follow-up calls (no status or activities query)
        self.assertEqual(mock_urlopen.call_count, 1)
        self.assertEqual(mock_urlopen.call_args_list[0][0][0].get_method(), "POST")
        # Session id is preserved in memory and on the returned result
        self.assertEqual(res.session_id, "sess-fail-write")
        self.assertTrue(res.is_error)
        self.assertEqual(res.failure_type, "audit_persistence_failure")
        self.assertFalse(res.complete)
        self.assertFalse(res.parsed["complete"])
        self.assertEqual(res.files_changed, [])
        self.assertIn("Simulated audit disk write failure", res.error_message)
        # Ensure status and activities were not queried
        self.assertEqual(res.status, {"state": "AUDIT_FAILED", "queried": False, "audit_failure": True})
        self.assertEqual(res.activities, {"queried": False, "activities": []})

    @patch("urllib.request.urlopen")
    def test_jules_coder_result_compatibility_and_attributes(self, mock_urlopen):
        """Verify Jules output adheres to CoderResult and exposes all expected attributes at top-level and parsed level."""
        from swe_af.execution.schemas import CoderResult

        resp_session = MagicMock()
        resp_session.read.return_value = b'{"name": "sessions/sess-coder", "id": "sess-coder", "state": "COMPLETED"}'
        resp_status = MagicMock()
        resp_status.read.return_value = b'{"name": "sessions/sess-coder", "state": "COMPLETED"}'
        resp_result = MagicMock()
        resp_result.read.return_value = b'{"activities": [{"id": "act-1", "files_changed": ["src/fix.py"]}]}'

        mock_urlopen.side_effect = [
            MagicMock(__enter__=MagicMock(return_value=resp_session), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_status), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_result), __exit__=MagicMock()),
        ]

        agent = JulesHarnessAgent()
        res = asyncio.run(agent.harness("Implement feature in worktree", schema=CoderResult))

        # Level 1: Parsed CoderResult schema object
        self.assertIsInstance(res.parsed, CoderResult)
        self.assertTrue(res.parsed.complete)
        self.assertIn("sess-coder", res.parsed.summary)
        self.assertEqual(res.parsed.files_changed, ["src/fix.py"])
        dumped = res.parsed.model_dump()
        self.assertIn("complete", dumped)
        self.assertIn("summary", dumped)
        self.assertIn("files_changed", dumped)

        # Level 2: Top-level HarnessResult (SimpleNamespace) attributes
        self.assertTrue(res.complete)
        self.assertEqual(res.files_changed, ["src/fix.py"])
        self.assertIn("sess-coder", res.summary)
        self.assertEqual(res.model, "jules")
        self.assertEqual(res.session_id, "sess-coder")
        self.assertFalse(res.is_error)
        self.assertEqual(res.failure_type, "none")
        self.assertIsNone(res.error_message)

        # Token counters
        self.assertGreater(res.input_tokens, 0)
        self.assertGreater(res.output_tokens, 0)
        self.assertEqual(res.total_tokens, res.input_tokens + res.output_tokens)
        self.assertEqual(res.cache_read_tokens, 0)
        self.assertEqual(res.cache_creation_tokens, 0)

    @patch("urllib.request.urlopen")
    def test_run_coder_integrates_cleanly_with_jules_backend(self, mock_urlopen):
        """Verify that run_coder execution reasoner functions end-to-end with SWE_HARNESS_BACKEND=jules."""
        import tempfile
        import swe_af.app  # ensures router is attached
        from swe_af.reasoners.execution_agents import run_coder

        resp_session = MagicMock()
        resp_session.read.return_value = b'{"name": "sessions/sess-rc", "id": "sess-rc", "state": "COMPLETED"}'
        resp_status = MagicMock()
        resp_status.read.return_value = b'{"name": "sessions/sess-rc", "state": "COMPLETED"}'
        resp_result = MagicMock()
        resp_result.read.return_value = b'{"activities": []}'

        mock_urlopen.side_effect = [
            MagicMock(__enter__=MagicMock(return_value=resp_session), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_status), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_result), __exit__=MagicMock()),
        ]

        old_backend = os.environ.get("SWE_HARNESS_BACKEND")
        os.environ["SWE_HARNESS_BACKEND"] = "jules"
        try:
            with tempfile.TemporaryDirectory() as td:
                res = asyncio.run(
                    run_coder(
                        issue={"name": "daily-task-1", "title": "Implement feature", "description": "Fix bug in app"},
                        worktree_path=td,
                        iteration=1,
                        iteration_id="iter-001",
                    )
                )
            self.assertTrue(res["complete"])
            self.assertIn("sess-rc", res["summary"])
            self.assertEqual(res["iteration_id"], "iter-001")
            self.assertEqual(res["files_changed"], [])
        finally:
            if old_backend is not None:
                os.environ["SWE_HARNESS_BACKEND"] = old_backend
            else:
                os.environ.pop("SWE_HARNESS_BACKEND", None)

    @patch("urllib.request.urlopen")
    def test_no_silent_fallback_on_jules_http_error(self, mock_urlopen):
        """Verify that Jules backend failures fail-closed without silent fallback to another agent."""
        import io, urllib.error
        from swe_af.runtime.application_harness import dispatch_harness
        import swe_af.app

        err_body = io.BytesIO(b'{"error": {"code": 401, "message": "Unauthorized API key"}}')
        http_err = urllib.error.HTTPError(
            url="https://jules.googleapis.com/v1alpha/sessions",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=err_body,
        )
        mock_urlopen.side_effect = http_err

        old_backend = os.environ.get("SWE_HARNESS_BACKEND")
        os.environ["SWE_HARNESS_BACKEND"] = "jules"
        try:
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    dispatch_harness(
                        swe_af.app.app,
                        prompt="Task requiring auth",
                    )
                )
            self.assertIn("HTTP error 401", str(ctx.exception))
            # Exactly one request attempt; no fallback to AgentField or secondary calls
            self.assertEqual(mock_urlopen.call_count, 1)
        finally:
            if old_backend is not None:
                os.environ["SWE_HARNESS_BACKEND"] = old_backend
            else:
                os.environ.pop("SWE_HARNESS_BACKEND", None)

    @patch("urllib.request.urlopen")
    def test_audit_log_strict_metadata_isolation(self, mock_urlopen):
        """Verify that audit log lines contain strictly the allowed metadata keys and NO prompt/secrets."""
        import json, tempfile
        from pathlib import Path

        resp_session = MagicMock()
        resp_session.read.return_value = b'{"name": "sessions/sess-audit-spec", "id": "sess-audit-spec"}'
        resp_status = MagicMock()
        resp_status.read.return_value = b'{"state": "COMPLETED"}'
        resp_result = MagicMock()
        resp_result.read.return_value = b'{"activities": []}'

        mock_urlopen.side_effect = [
            MagicMock(__enter__=MagicMock(return_value=resp_session), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_status), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_result), __exit__=MagicMock()),
        ]

        with tempfile.TemporaryDirectory() as td:
            audit_file = Path(td) / "strict_audit.jsonl"
            agent = JulesHarnessAgent(audit_path=audit_file)
            secret_prompt = "CONFIDENTIAL_TASK_PROMPT_ABC123"
            res = asyncio.run(agent.harness(secret_prompt))

            self.assertEqual(res.session_id, "sess-audit-spec")
            self.assertTrue(audit_file.is_file())

            lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)

            entry = json.loads(lines[0])
            allowed_keys = {"timestamp_utc", "session_id", "event", "outcome", "version"}
            self.assertEqual(set(entry.keys()), allowed_keys)
            self.assertEqual(entry["session_id"], "sess-audit-spec")
            self.assertEqual(entry["event"], "session_created")
            self.assertEqual(entry["outcome"], "created")
            self.assertEqual(entry["version"], "1.0")

            # Content verification: NO secrets, NO prompts, NO headers in raw log line
            raw_line = lines[0]
            self.assertNotIn(secret_prompt, raw_line)
            self.assertNotIn("mock-harness-key", raw_line)
            self.assertNotIn("x-goog-api-key", raw_line.lower())
            self.assertNotIn("authorization", raw_line.lower())

    @patch("urllib.request.urlopen")
    def test_async_polling_transitions_queued_in_progress_completed(self, mock_urlopen):
        """Verify async polling lifecycle through intermediate states to terminal completion."""
        from swe_af.execution.schemas import CoderResult

        resp_session = MagicMock()
        resp_session.read.return_value = b'{"name": "sessions/sess-async-poll", "id": "sess-async-poll", "state": "QUEUED"}'

        resp_poll_1 = MagicMock()
        resp_poll_1.read.return_value = b'{"name": "sessions/sess-async-poll", "state": "PLANNING"}'

        resp_poll_2 = MagicMock()
        resp_poll_2.read.return_value = b'{"name": "sessions/sess-async-poll", "state": "IN_PROGRESS"}'

        resp_poll_3 = MagicMock()
        resp_poll_3.read.return_value = b'{"name": "sessions/sess-async-poll", "state": "COMPLETED"}'

        resp_result = MagicMock()
        resp_result.read.return_value = b'{"activities": [{"id": "act-1", "files_changed": ["swe_af/app.py"]}]}'

        mock_urlopen.side_effect = [
            MagicMock(__enter__=MagicMock(return_value=resp_session), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_poll_1), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_poll_2), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_poll_3), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_result), __exit__=MagicMock()),
        ]

        agent = JulesHarnessAgent()
        res = asyncio.run(agent.harness("Refactor app lifecycle", schema=CoderResult, poll_interval=0.001))

        self.assertEqual(res.session_id, "sess-async-poll")
        self.assertEqual(res.status["state"], "COMPLETED")
        self.assertFalse(res.is_error)
        self.assertEqual(res.failure_type, "none")
        self.assertIsInstance(res.parsed, CoderResult)
        self.assertTrue(res.parsed.complete)
        self.assertEqual(res.parsed.files_changed, ["swe_af/app.py"])
        self.assertEqual(mock_urlopen.call_count, 5)

    @patch("urllib.request.urlopen")
    def test_polling_timeout_terminates_and_marks_failure(self, mock_urlopen):
        """Verify that polling exceeding deadline stops cleanly and marks timeout failure without hanging."""
        resp_session = MagicMock()
        resp_session.read.return_value = b'{"name": "sessions/sess-timeout", "id": "sess-timeout", "state": "QUEUED"}'

        resp_poll = MagicMock()
        resp_poll.read.return_value = b'{"name": "sessions/sess-timeout", "state": "IN_PROGRESS"}'

        def fake_urlopen(req, *args, **kwargs):
            if req.get_method() == "POST":
                return MagicMock(__enter__=MagicMock(return_value=resp_session), __exit__=MagicMock())
            return MagicMock(__enter__=MagicMock(return_value=resp_poll), __exit__=MagicMock())

        mock_urlopen.side_effect = fake_urlopen

        agent = JulesHarnessAgent()
        res = asyncio.run(agent.harness("Stuck task", poll_timeout=0.02, poll_interval=0.005))

        self.assertEqual(res.session_id, "sess-timeout")
        self.assertTrue(res.is_error)
        self.assertEqual(res.failure_type, "timeout")
        self.assertIn("timed out", res.error_message.lower())
        self.assertFalse(res.parsed["complete"])
        self.assertEqual(res.status["state"], "IN_PROGRESS")
        self.assertTrue(res.activities.get("timeout"))

    @patch("urllib.request.urlopen")
    def test_terminal_failure_stops_polling_fail_closed(self, mock_urlopen):
        """Verify that remote failure state stops polling immediately and returns fail-closed outcome."""
        resp_session = MagicMock()
        resp_session.read.return_value = b'{"name": "sessions/sess-fail", "id": "sess-fail", "state": "QUEUED"}'

        resp_status = MagicMock()
        resp_status.read.return_value = b'{"name": "sessions/sess-fail", "state": "FAILED"}'

        resp_result = MagicMock()
        resp_result.read.return_value = b'{"activities": [{"id": "err-1", "description": "Syntax error in build"}]}'

        mock_urlopen.side_effect = [
            MagicMock(__enter__=MagicMock(return_value=resp_session), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_status), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_result), __exit__=MagicMock()),
        ]

        agent = JulesHarnessAgent()
        res = asyncio.run(agent.harness("Task that fails remotely", poll_interval=0.001))

        self.assertEqual(res.session_id, "sess-fail")
        self.assertEqual(res.status["state"], "FAILED")
        self.assertTrue(res.is_error)
        self.assertEqual(res.failure_type, "session_failed")
        self.assertFalse(res.parsed["complete"])
        self.assertIn("FAILED", res.summary)
        # Polling stopped immediately at 3 calls without continuing
        self.assertEqual(mock_urlopen.call_count, 3)

    @patch("urllib.request.urlopen")
    def test_wait_for_completion_false_prevents_premature_complete(self, mock_urlopen):
        """Verify that when wait_for_completion=False and state is in-progress, complete is FALSE."""
        resp_session = MagicMock()
        resp_session.read.return_value = b'{"name": "sessions/sess-nonterm", "id": "sess-nonterm", "state": "QUEUED"}'

        resp_status = MagicMock()
        resp_status.read.return_value = b'{"name": "sessions/sess-nonterm", "state": "ACTIVE"}'

        resp_result = MagicMock()
        resp_result.read.return_value = b'{"activities": []}'

        mock_urlopen.side_effect = [
            MagicMock(__enter__=MagicMock(return_value=resp_session), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_status), __exit__=MagicMock()),
            MagicMock(__enter__=MagicMock(return_value=resp_result), __exit__=MagicMock()),
        ]

        agent = JulesHarnessAgent()
        res = asyncio.run(agent.harness("Fire and query task", wait_for_completion=False))

        self.assertEqual(res.session_id, "sess-nonterm")
        self.assertEqual(res.status["state"], "ACTIVE")
        # Defect prevention: in-progress tasks MUST NEVER report complete=True prematurely
        self.assertFalse(res.parsed["complete"])
        self.assertFalse(res.is_error)
        self.assertEqual(mock_urlopen.call_count, 3)

    @patch("urllib.request.urlopen")
    def test_async_io_does_not_block_event_loop(self, mock_urlopen):
        """Regression: synchronous urllib calls run in worker threads and do NOT block asyncio event loop."""
        import time

        resp_session = MagicMock()
        resp_session.read.return_value = b'{"name": "sessions/sess-async-io", "id": "sess-async-io", "state": "COMPLETED"}'

        resp_status = MagicMock()
        resp_status.read.return_value = b'{"name": "sessions/sess-async-io", "state": "COMPLETED"}'

        resp_result = MagicMock()
        resp_result.read.return_value = b'{"activities": []}'

        def fake_urlopen_with_delay(req, *args, **kwargs):
            # Simulate blocking network I/O
            time.sleep(0.04)
            url = req.full_url
            if "/activities" in url:
                return MagicMock(__enter__=MagicMock(return_value=resp_result), __exit__=MagicMock())
            elif "sessions/" in url:
                return MagicMock(__enter__=MagicMock(return_value=resp_status), __exit__=MagicMock())
            return MagicMock(__enter__=MagicMock(return_value=resp_session), __exit__=MagicMock())

        mock_urlopen.side_effect = fake_urlopen_with_delay

        async def run_concurrently():
            agent = JulesHarnessAgent()
            ticks = 0

            async def ticker():
                nonlocal ticks
                for _ in range(20):
                    await asyncio.sleep(0.005)
                    ticks += 1

            ticker_task = asyncio.create_task(ticker())
            harness_task = asyncio.create_task(agent.harness("Task with network latency"))
            res, _ = await asyncio.gather(harness_task, ticker_task)
            return res, ticks

        result, ticks_counted = asyncio.run(run_concurrently())
        self.assertEqual(result.session_id, "sess-async-io")
        self.assertTrue(result.parsed["complete"])
        # If event loop was blocked synchronously by time.sleep, ticker would not have made progress
        self.assertGreater(ticks_counted, 2, "Event loop was starved/blocked by synchronous network call")

    @patch("urllib.request.urlopen")
    def test_status_query_failure_halts_flow_without_calling_activities(self, mock_urlopen):
        """Regression: status failure immediately interrupts remote flow and NEVER calls activities endpoint."""
        import io, urllib.error

        resp_session = MagicMock()
        resp_session.read.return_value = b'{"name": "sessions/sess-status-fail", "id": "sess-status-fail"}'

        err_body = io.BytesIO(b'{"error": {"code": 500, "message": "Backend status unavailable"}}')
        status_err = urllib.error.HTTPError(
            url="https://jules.googleapis.com/v1alpha/sessions/sess-status-fail",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=err_body,
        )

        mock_urlopen.side_effect = [
            MagicMock(__enter__=MagicMock(return_value=resp_session), __exit__=MagicMock()),
            status_err,  # Status call fails
        ]

        agent = JulesHarnessAgent()
        res = asyncio.run(agent.harness("Status failure task"))

        # Preserves session identifier
        self.assertEqual(res.session_id, "sess-status-fail")
        # Diagnostic message sanitized and preserved
        self.assertTrue(res.status.get("unconfirmed"))
        self.assertIn("500", res.status.get("error", ""))
        self.assertIn("Backend status unavailable", res.status.get("error", ""))
        # Fail-closed
        self.assertTrue(res.is_error)
        self.assertEqual(res.failure_type, "status_query_error")
        self.assertFalse(res.parsed["complete"])
        # CRITICAL: exactly 2 calls made (POST create, GET status); activities endpoint was NEVER called
        self.assertEqual(mock_urlopen.call_count, 2)
        self.assertEqual(res.activities, {"unconfirmed": True, "activities": []})

    def test_audit_log_enforces_0600_permissions_on_preexisting_file(self):
        """Regression: audit logger enforces 0600 permissions also for preexisting log files."""
        import os, stat, tempfile
        from pathlib import Path
        from swe_af.runtime.jules_adapter import _persist_session_audit

        with tempfile.TemporaryDirectory() as td:
            audit_file = Path(td) / "preexisting_audit.jsonl"
            # Create preexisting file with lax permissions
            audit_file.write_text('{"init": true}\n', encoding="utf-8")
            try:
                os.chmod(audit_file, 0o644)
            except (OSError, NotImplementedError):
                pass

            _persist_session_audit("sess-preexist-1", outcome="created", log_path=audit_file)

            # Check that file now has 0600 on POSIX platforms
            if os.name == "posix":
                current_mode = stat.S_IMODE(audit_file.stat().st_mode)
                self.assertEqual(current_mode, 0o600)

            lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn("sess-preexist-1", lines[1])

        # Test OS limitation handling (e.g. OSError / NotImplementedError during chmod)
        with tempfile.TemporaryDirectory() as td:
            audit_file = Path(td) / "os_limitation_audit.jsonl"
            audit_file.write_text('{"init": true}\n', encoding="utf-8")
            with patch("os.chmod", side_effect=OSError("Operation not permitted")):
                # Must not raise or crash
                _persist_session_audit("sess-preexist-os-err", outcome="created", log_path=audit_file)

            lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn("sess-preexist-os-err", lines[1])


if __name__ == "__main__":
    unittest.main()
