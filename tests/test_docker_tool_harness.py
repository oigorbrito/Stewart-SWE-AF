"""Tests for the docker-tool harness backend registration and dispatching."""

from __future__ import annotations

import pathlib
import pytest

from swe_af.runtime.docker_tool_harness import (
    DOCKER_TOOL_BACKEND,
    register_docker_tool_backend,
    _docker_tool_handler,
)
from swe_af.runtime.docker_tool_executor import DockerSafeToolExecutor
from swe_af.runtime.tool_executor import ToolExecutionResult
from swe_af.runtime.application_harness import (
    dispatch_harness as app_dispatch,
    HarnessBackendUnavailable,
    DEFAULT_BACKEND,
)
from swe_af.runtime.harness_dispatch import (
    HarnessBackendRegistration,
    HarnessDispatcher,
    dispatch_harness as dispatch_boundary,
)


@pytest.fixture(autouse=True)
def setup_backend():
    register_docker_tool_backend()


@pytest.mark.asyncio
async def test_default_backend_remains_agentfield_when_unset(monkeypatch):
    monkeypatch.delenv("SWE_HARNESS_BACKEND", raising=False)
    seen = []
    expected_result = object()

    class Agent:
        async def harness(self, *args, **kwargs):
            seen.append((args, kwargs))
            return expected_result

    returned = await app_dispatch(Agent(), "default prompt")
    assert returned is expected_result
    assert len(seen) == 1
    assert DEFAULT_BACKEND == "agentfield"


@pytest.mark.asyncio
async def test_unknown_backend_fails_without_fallback(monkeypatch):
    monkeypatch.setenv("SWE_HARNESS_BACKEND", "non-existent-backend")

    class Agent:
        async def harness(self, *args, **kwargs):
            raise AssertionError("AgentField must not be called")

    with pytest.raises(HarnessBackendUnavailable, match="no fallback was attempted"):
        await app_dispatch(Agent(), "test prompt")


@pytest.mark.asyncio
async def test_docker_tool_rejects_unsupported_tool(tmp_path: pathlib.Path, monkeypatch):
    monkeypatch.setenv("SWE_HARNESS_BACKEND", DOCKER_TOOL_BACKEND)

    class Agent:
        async def harness(self, *args, **kwargs):
            raise AssertionError("AgentField must not be called")

    options = {
        "tools": ["Bash"],
        "cwd": str(tmp_path),
    }

    with pytest.raises(ValueError, match="docker-tool does not support tool: Bash"):
        await app_dispatch(Agent(), "bash prompt", **options)


@pytest.mark.asyncio
async def test_docker_tool_rejects_missing_workspace(monkeypatch):
    monkeypatch.setenv("SWE_HARNESS_BACKEND", DOCKER_TOOL_BACKEND)

    class Agent:
        async def harness(self, *args, **kwargs):
            raise AssertionError("AgentField must not be called")

    with pytest.raises(ValueError, match="requires cwd or project_dir"):
        await app_dispatch(Agent(), "prompt", tools=["Write"])


@pytest.mark.asyncio
async def test_docker_tool_propagates_executor_failure(tmp_path: pathlib.Path, monkeypatch):
    monkeypatch.setenv("SWE_HARNESS_BACKEND", DOCKER_TOOL_BACKEND)

    class FailingExecutor(DockerSafeToolExecutor):
        async def execute(self, invocation, *, context):
            return ToolExecutionResult(
                stdout="",
                stderr="simulated container crash",
                exit_code=137,
            )

    failing_executor = FailingExecutor()

    # Test via _docker_tool_handler directly with custom executor
    from swe_af.runtime.application_harness import HarnessRequest
    req = HarnessRequest.create(
        "failing prompt",
        {"cwd": str(tmp_path), "tools": ["Write"], "tool_args": {"path": "a.txt", "content": "c"}},
    )

    class DummyAgent:
        async def harness(self, *args, **kwargs): pass

    with pytest.raises(RuntimeError, match="Tool execution failed: simulated container crash"):
        await _docker_tool_handler(DummyAgent(), req, tool_executor=failing_executor)


@pytest.mark.asyncio
async def test_docker_tool_success_with_mocked_executor(tmp_path: pathlib.Path, monkeypatch):
    class SuccessExecutor(DockerSafeToolExecutor):
        async def execute(self, invocation, *, context):
            return ToolExecutionResult(
                stdout="successfully wrote 4 bytes to test.txt",
                stderr="",
                exit_code=0,
            )

    success_executor = SuccessExecutor()

    from swe_af.runtime.application_harness import HarnessRequest
    req = HarnessRequest.create(
        "success prompt",
        {"cwd": str(tmp_path), "tools": ["Write"], "tool_args": {"path": "test.txt", "content": "data"}},
    )

    class DummyAgent:
        async def harness(self, *args, **kwargs): pass

    outcome = await _docker_tool_handler(DummyAgent(), req, tool_executor=success_executor)
    assert outcome.is_error is False
    assert outcome.parsed["ok"] is True
    assert outcome.parsed["executed_tools"][0]["exit_code"] == 0
    assert "successfully wrote" in outcome.parsed["executed_tools"][0]["stdout"]


@pytest.mark.asyncio
async def test_docker_tool_compatible_with_harness_dispatcher(tmp_path: pathlib.Path, monkeypatch):
    monkeypatch.setenv("SWE_HARNESS_BACKEND", DOCKER_TOOL_BACKEND)

    class MockSafeExecutor(DockerSafeToolExecutor):
        async def execute(self, invocation, *, context):
            return ToolExecutionResult(
                stdout="ok from harness_dispatch",
                exit_code=0,
            )

    registration = HarnessBackendRegistration(
        handler=_docker_tool_handler,
        tool_executor=MockSafeExecutor(),
    )
    dispatcher = HarnessDispatcher({DOCKER_TOOL_BACKEND: registration})

    class Agent:
        async def harness(self, *args, **kwargs):
            raise AssertionError("AgentField must not be called")

    options = {
        "tools": ["Write"],
        "cwd": str(tmp_path),
        "tool_args": {"path": "disp.txt", "content": "disp"},
    }

    outcome = await dispatch_boundary(
        Agent(),
        "prompt to boundary",
        harness_dispatcher=dispatcher,
        **options,
    )
    assert outcome.is_error is False
    assert outcome.parsed["ok"] is True
    assert outcome.parsed["executed_tools"][0]["stdout"] == "ok from harness_dispatch"
