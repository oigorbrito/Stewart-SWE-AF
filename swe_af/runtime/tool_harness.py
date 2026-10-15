"""Tool-enabled local harness backend using CandidateSafeToolExecutor.

Enables secure local execution of the 'Write' tool within a validated workspace
when explicitly selected via SWE_HARNESS_BACKEND=local-tool.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from swe_af.runtime.candidate_tool_executor import CandidateSafeToolExecutor
from swe_af.runtime.tool_executor import (
    ToolExecutionContext,
    ToolInvocation,
)
from swe_af.runtime.application_harness import (
    HarnessAgent,
    HarnessRequest,
    register_backend,
)

LOCAL_TOOL_BACKEND = "local-tool"
_TOOL_EXECUTOR = CandidateSafeToolExecutor()


async def _local_tool_handler(
    _agent: HarnessAgent,
    request: HarnessRequest,
) -> Any:
    workspace_dir = request.options.get("cwd") or request.options.get("project_dir")
    if not workspace_dir:
        raise ValueError("local-tool execution requires cwd or project_dir workspace context")

    tools = request.options.get("tools") or []
    # Validate that all requested tools are allowed
    for tool in tools:
        if tool != "Write":
            raise ValueError(f"local-tool does not support tool: {tool}")

    messages = [{"role": "user", "content": request.prompt}]

    executed_results = []
    if "Write" in tools:
        args = request.options.get("tool_args", {"path": "output.txt", "content": request.prompt})
        invocation = ToolInvocation(
            invocation_id="inv-tool-local-1",
            name="Write",
            arguments=args,
        )
        context = ToolExecutionContext(
            workspace_root=workspace_dir,
            timeout_seconds=float(request.options.get("timeout_seconds") or 10.0),
            max_output_bytes=64 * 1024,
        )
        _TOOL_EXECUTOR.validate_arguments(invocation, context=context)
        exec_result = await _TOOL_EXECUTOR.execute(invocation, context=context)
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
        duration_ms=5,
        session_id="local-tool-session",
        messages=messages,
        input_tokens=len(request.prompt.split()),
        output_tokens=len(serialized.split()),
        cache_read_tokens=0,
        cache_creation_tokens=0,
        total_tokens=len(request.prompt.split()) + len(serialized.split()),
        model="local-tool-executor",
    )


def register_local_tool_backend() -> None:
    """Register the local-tool backend in the application-owned dispatch registry."""
    register_backend(LOCAL_TOOL_BACKEND, _local_tool_handler)
