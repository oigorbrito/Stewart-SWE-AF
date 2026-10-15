"""Contract tests for explicit, fail-closed harness dispatch."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from swe_af.runtime.harness_dispatch import (
    DEFAULT_HARNESS_BACKEND,
    HarnessBackendConfigurationError,
    HarnessBackendRegistration,
    HarnessDispatcher,
    HarnessExecutionRequest,
    HarnessToolExecutorUnavailable,
    dispatch_harness,
)


@pytest.mark.parametrize("provider", ["claude-code", "opencode", "codex"])
@pytest.mark.parametrize("backend_setting", [None, "agentfield"])
@pytest.mark.asyncio
async def test_agentfield_default_preserves_request_and_result(
    provider, backend_setting, monkeypatch
):
    if backend_setting is None:
        monkeypatch.delenv("SWE_HARNESS_BACKEND", raising=False)
    else:
        monkeypatch.setenv("SWE_HARNESS_BACKEND", backend_setting)
    schema = type("ResultSchema", (), {})
    tools = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
    env = {"SAFE_TEST_VALUE": "fixture"}
    options = {
        "provider": provider,
        "model": "role-specific-model",
        "schema": schema,
        "tools": tools,
        "cwd": "/tmp/worktree",
        "project_dir": "/tmp/workspace",
        "permission_mode": "workspace-write",
        "timeout_seconds": 17,
        "system_prompt": "fixture system prompt",
        "max_turns": 9,
        "max_retries": 0,
        "schema_max_retries": 0,
        "env": env,
    }
    request = HarnessExecutionRequest.create("fixture prompt", options)

    assert request.prompt == "fixture prompt"
    assert request.provider == provider
    assert request.model == "role-specific-model"
    assert request.schema is schema
    assert request.tools is tools
    assert request.cwd == "/tmp/worktree"
    assert request.project_dir == "/tmp/workspace"
    assert request.permission_mode == "workspace-write"
    assert request.timeout_seconds == 17
    assert request.system_prompt == "fixture system prompt"
    assert request.agentfield_options() == options
    assert request.agentfield_options()["env"] is env

    result = SimpleNamespace(
        result='{"ok":true}',
        parsed={"ok": True},
        is_error=False,
        error_message=None,
        failure_type="none",
        cost_usd=None,
        num_turns=2,
        duration_ms=31,
        session_id="fixture-session",
        messages=[],
        input_tokens=12,
        output_tokens=4,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        total_tokens=16,
        model="role-specific-model",
    )
    seen = {}

    class FixtureAgent:
        async def harness(self, prompt, **kwargs):
            seen["prompt"] = prompt
            seen["kwargs"] = kwargs
            return result

    returned = await dispatch_harness(FixtureAgent(), "fixture prompt", **options)

    assert seen == {"prompt": "fixture prompt", "kwargs": options}
    assert returned is result
    assert returned.parsed == {"ok": True}
    assert returned.cost_usd is None
    assert returned.input_tokens == 12
    assert returned.output_tokens == 4


@pytest.mark.parametrize("prompt_as_keyword", [False, True])
@pytest.mark.asyncio
async def test_agentfield_default_preserves_prompt_call_shape(
    prompt_as_keyword, monkeypatch
):
    monkeypatch.delenv("SWE_HARNESS_BACKEND", raising=False)
    seen = {}
    result = object()

    class FixtureAgent:
        async def harness(self, *args, **kwargs):
            seen["args"] = args
            seen["kwargs"] = kwargs
            return result

    if prompt_as_keyword:
        returned = await dispatch_harness(
            FixtureAgent(), prompt="named prompt", provider="codex"
        )
        assert seen == {
            "args": (),
            "kwargs": {"prompt": "named prompt", "provider": "codex"},
        }
    else:
        returned = await dispatch_harness(
            FixtureAgent(), "positional prompt", provider="codex"
        )
        assert seen == {"args": ("positional prompt",), "kwargs": {"provider": "codex"}}
    assert returned is result


@pytest.mark.asyncio
async def test_explicit_backend_is_selected_by_application_configuration(monkeypatch):
    monkeypatch.setenv("SWE_HARNESS_BACKEND", "fixture-backend")
    result = object()
    selected = {}

    async def configured_backend(agent, request, tool_executor):
        selected["agent"] = agent
        selected["request"] = request
        selected["tool_executor"] = tool_executor
        return result

    class FixtureAgent:
        async def harness(self, prompt, **kwargs):
            raise AssertionError("AgentField must not be selected")

    agent = FixtureAgent()
    dispatcher = HarnessDispatcher(
        {"fixture-backend": HarnessBackendRegistration(handler=configured_backend)}
    )
    returned = await dispatch_harness(
        agent,
        prompt="fixture prompt",
        provider="opencode",
        model="fixture-model",
        harness_dispatcher=dispatcher,
    )

    assert returned is result
    assert selected["agent"] is agent
    assert selected["request"].provider == "opencode"
    assert selected["request"].model == "fixture-model"
    assert selected["request"].prompt == "fixture prompt"
    assert selected["tool_executor"] is None


@pytest.mark.asyncio
async def test_unknown_backend_fails_without_fallback(monkeypatch):
    monkeypatch.setenv("SWE_HARNESS_BACKEND", "typo-backend")

    class FixtureAgent:
        calls = 0

        async def harness(self, prompt, **kwargs):
            self.calls += 1
            return object()

    agent = FixtureAgent()
    with pytest.raises(
        HarnessBackendConfigurationError, match="typo-backend.*not registered"
    ):
        await dispatch_harness(agent, "fixture", provider="opencode")
    assert agent.calls == 0


@pytest.mark.asyncio
async def test_configured_backend_without_handler_fails_clearly(monkeypatch):
    monkeypatch.setenv("SWE_HARNESS_BACKEND", "missing-handler")
    dispatcher = HarnessDispatcher({})

    with pytest.raises(
        HarnessBackendConfigurationError, match="missing-handler.*not registered"
    ):
        await dispatch_harness(object(), "fixture", harness_dispatcher=dispatcher)


@pytest.mark.asyncio
async def test_backend_selection_is_isolated_between_dispatcher_instances(monkeypatch):
    monkeypatch.setenv("SWE_HARNESS_BACKEND", "same-name")
    returned_values = (object(), object())

    async def handler_a(agent, request, tool_executor):
        return returned_values[0]

    async def handler_b(agent, request, tool_executor):
        return returned_values[1]

    registration_a = HarnessBackendRegistration(handler=handler_a)
    registration_b = HarnessBackendRegistration(handler=handler_b)
    dispatcher_a = HarnessDispatcher({"same-name": registration_a})
    dispatcher_b = HarnessDispatcher({"same-name": registration_b})

    result_a = await dispatch_harness(
        object(), "fixture", harness_dispatcher=dispatcher_a
    )
    result_b = await dispatch_harness(
        object(), "fixture", harness_dispatcher=dispatcher_b
    )

    assert result_a is returned_values[0]
    assert result_b is returned_values[1]
    assert DEFAULT_HARNESS_BACKEND == "agentfield"


@pytest.mark.asyncio
async def test_alternative_backend_cannot_receive_tools_without_safe_executor(
    monkeypatch,
):
    monkeypatch.setenv("SWE_HARNESS_BACKEND", "tool-backend")
    calls = 0

    async def handler(agent, request, tool_executor):
        nonlocal calls
        calls += 1
        return object()

    dispatcher = HarnessDispatcher(
        {"tool-backend": HarnessBackendRegistration(handler=handler)}
    )
    with pytest.raises(HarnessToolExecutorUnavailable, match="no SafeToolExecutor"):
        await dispatch_harness(
            object(),
            "tool prompt",
            tools=["Bash", "Read"],
            harness_dispatcher=dispatcher,
        )
    assert calls == 0


@pytest.mark.asyncio
async def test_invalid_empty_backend_setting_fails_closed(monkeypatch):
    monkeypatch.setenv("SWE_HARNESS_BACKEND", "  ")
    with pytest.raises(HarnessBackendConfigurationError, match="set but empty"):
        await dispatch_harness(object(), "fixture")


@pytest.mark.asyncio
async def test_dispatch_propagates_agentfield_failure_without_retry(monkeypatch):
    monkeypatch.delenv("SWE_HARNESS_BACKEND", raising=False)
    failure = RuntimeError("fixture provider failure")

    class FixtureAgent:
        calls = 0

        async def harness(self, prompt, **kwargs):
            self.calls += 1
            raise failure

    agent = FixtureAgent()
    with pytest.raises(RuntimeError, match="fixture provider failure"):
        await dispatch_harness(agent, "fixture", provider="opencode", model="fixed")
    assert agent.calls == 1


@pytest.mark.asyncio
async def test_dispatch_propagates_cancellation(monkeypatch):
    monkeypatch.delenv("SWE_HARNESS_BACKEND", raising=False)
    cancelled = asyncio.CancelledError()

    class FixtureAgent:
        async def harness(self, prompt, **kwargs):
            raise cancelled

    with pytest.raises(asyncio.CancelledError):
        await dispatch_harness(FixtureAgent(), "fixture", provider="codex")


def test_compose_passes_backend_selection_to_application_containers():
    root = Path(__file__).resolve().parents[1]
    for filename in ("docker-compose.yml", "docker-compose.local.yml"):
        compose = (root / filename).read_text(encoding="utf-8")
        assert "SWE_HARNESS_BACKEND=${SWE_HARNESS_BACKEND-agentfield}" in compose
