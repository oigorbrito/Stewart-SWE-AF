"""Tool-enabled Docker harness backend using DockerSafeToolExecutor.

Enables secure execution of the 'Write' tool within an isolated, disposable
Docker container when explicitly selected via SWE_HARNESS_BACKEND=docker-tool.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from swe_af.runtime.docker_tool_executor import DockerSafeToolExecutor
from swe_af.runtime.tool_executor import (
    SafeToolExecutor,
    ToolExecutionContext,
    ToolInvocation,
)
from swe_af.runtime.application_harness import (
    HarnessAgent,
    HarnessRequest,
    register_backend,
)

DOCKER_TOOL_BACKEND = "docker-tool"
_TOOL_EXECUTOR = DockerSafeToolExecutor()


async def _docker_tool_handler(
    _agent: HarnessAgent,
    request: HarnessRequest,
    tool_executor: SafeToolExecutor | None = None,
) -> Any:
    workspace_dir = request.options.get("cwd") or request.options.get("project_dir")
    if not workspace_dir:
        raise ValueError("docker-tool execution requires cwd or project_dir workspace context")

    tools = request.options.get("tools") or []
    for tool in tools:
        if tool != "Write":
            raise ValueError(f"docker-tool does not support tool: {tool}")

    executor = tool_executor if tool_executor is not None else _TOOL_EXECUTOR

    messages = [{"role": "user", "content": request.prompt}]
    executed_results = []

    if "Write" in tools:
        args = request.options.get("tool_args", {"path": "output.txt", "content": request.prompt})
        invocation = ToolInvocation(
            invocation_id="inv-tool-docker-1",
            name="Write",
            arguments=args,
        )
        context = ToolExecutionContext(
            workspace_root=Path(workspace_dir),
            timeout_seconds=float(request.options.get("timeout_seconds") or 10.0),
            max_output_bytes=64 * 1024,
        )
        executor.validate_arguments(invocation, context=context)
        exec_result = await executor.execute(invocation, context=context)
        executed_results.append({
            "tool": "Write",
            "arguments": dict(invocation.arguments),
            "exit_code": exec_result.exit_code,
            "stdout": exec_result.stdout,
            "stderr": exec_result.stderr,
        })
        if exec_result.exit_code != 0:
            raise RuntimeError(f"Tool execution failed: {exec_result.stderr}")

    result_payload = {
        "ok": True,
        "executed_tools": executed_results,
        "prompt": request.prompt,
    }
    serialized = json.dumps(result_payload)

    return SimpleNamespace(
        result=serialized,
        parsed=result_payload,
        is_error=False,
        error_message=None,
        failure_type="none",
        cost_usd=0.0,
        num_turns=1,
        duration_ms=10,
        session_id="docker-tool-session",
        messages=messages,
        input_tokens=len(request.prompt.split()),
        output_tokens=len(serialized.split()),
        cache_read_tokens=0,
        cache_creation_tokens=0,
        total_tokens=len(request.prompt.split()) + len(serialized.split()),
        model="docker-tool-executor",
    )


def register_docker_tool_backend() -> None:
    """Register the docker-tool backend in the application-owned dispatch registry."""
    register_backend(DOCKER_TOOL_BACKEND, _docker_tool_handler)
