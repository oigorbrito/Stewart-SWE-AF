"""End-to-end local Gemini-shaped fixture through SWE-AF issue + Git workflow.

Only the model-call boundary is replaced: SWE-AF's real coding loop,
worktree/branch/commit lifecycle, role-model resolution, and diff generation
remain active. All HTTP requests target a deterministic loopback fixture.
"""
from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from swe_af.issue.build import _implement_issue_impl
from tests.issue.conftest import run_git


def test_gemini_mock_issue_runtime_produces_reviewable_branch_diff(git_repo, monkeypatch):
    calls: list[dict] = []

    class FixtureHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            role = body.get("metadata", {}).get("sweaf_role")
            if role == "coder":
                message = {
                    "role": "assistant", "content": None,
                    "tool_calls": [{"id": "write-1", "type": "function", "function": {
                        "name": "write_file", "arguments": json.dumps({
                            "path": "feature.py", "content": "GEMINI_MOCK_RESULT = 'local-only'\n"
                        })}}],
                }
                finish_reason = "tool_calls"
            else:
                message = {"role": "assistant", "content": json.dumps({
                    "approved": True, "blocking": False, "summary": "deterministic mock review"
                })}
                finish_reason = "stop"
            payload = json.dumps({"id": "mock-response", "choices": [{
                "index": 0, "message": message, "finish_reason": finish_reason
            }], "usage": {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("SWE_DEFAULT_RUNTIME", "open_code")
    monkeypatch.setenv("SWE_DEFAULT_MODEL", "google-gemini-mock/gemini-mock-model")
    monkeypatch.setenv("HARNESS_MODEL", "google-gemini-mock/gemini-mock-model")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    async def mocked_harness_call(target: str, **kwargs):
        role = target.rsplit(".", 1)[-1]
        model = kwargs["model"]
        assert kwargs["ai_provider"] == "opencode"
        assert model == "google-gemini-mock/gemini-mock-model"
        request_body = {
            "model": model,
            "messages": [{"role": "user", "content": f"{role}: {kwargs.get('issue', {}).get('title', '')}"}],
            "metadata": {"sweaf_role": "coder" if role == "run_coder" else "reviewer"},
            "tools": ([{"type": "function", "function": {"name": "write_file",
                       "parameters": {"type": "object", "properties": {
                           "path": {"type": "string"}, "content": {"type": "string"}}}}}]
                      if role == "run_coder" else []),
            "stream": False,
        }
        raw = json.dumps(request_body).encode()
        req = Request(f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                      data=raw, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=2) as response:
            result = json.loads(response.read())
        message = result["choices"][0]["message"]
        if role == "run_coder":
            tool = message["tool_calls"][0]["function"]
            args = json.loads(tool["arguments"])
            destination = Path(kwargs["worktree_path"], args["path"]).resolve()
            assert Path(kwargs["worktree_path"]).resolve() in destination.parents
            destination.write_text(args["content"], encoding="utf-8")
            return {"files_changed": [args["path"]], "summary": "mock tool call applied", "complete": True}
        if role == "run_code_reviewer":
            return json.loads(message["content"])
        raise AssertionError(f"unexpected mocked LLM role {role}")

    try:
        result = asyncio.run(_implement_issue_impl(
            issue={"title": "Write fixture output", "description": "Create the requested marker file.",
                   "acceptance_criteria": ["feature.py contains the marker"], "files_to_create": ["feature.py"]},
            repo_path=git_repo, base_branch="main", artifacts_dir=".artifacts",
            additional_context="local fixture only",
            config={"runtime": "open_code", "verify": False, "enable_github_pr": False},
            call_fn=mocked_harness_call, note_fn=None, node_id="gemini-mock-test",
        ))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result["success"] is True
    assert result["base_branch"] == "main"
    assert "feature.py" in result["files_changed"]
    assert run_git(git_repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    diff = run_git(git_repo, "diff", "main", result["branch"], "--", "feature.py")
    assert "+GEMINI_MOCK_RESULT = 'local-only'" in diff
    assert len(calls) == 2
    assert {request["model"] for request in calls} == {"google-gemini-mock/gemini-mock-model"}
    assert [request["metadata"]["sweaf_role"] for request in calls] == ["coder", "reviewer"]
