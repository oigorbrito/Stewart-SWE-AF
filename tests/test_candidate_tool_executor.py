"""Tests for the CandidateSafeToolExecutor implementation."""

from __future__ import annotations

import asyncio
import pathlib
import pytest

from swe_af.runtime.candidate_tool_executor import CandidateSafeToolExecutor
from swe_af.runtime.tool_executor import (
    ToolExecutionContext,
    ToolInvocation,
)


@pytest.fixture
def workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "workspace"


@pytest.fixture
def context(workspace: pathlib.Path) -> ToolExecutionContext:
    workspace.mkdir(exist_ok=True)
    return ToolExecutionContext(
        workspace_root=workspace,
        timeout_seconds=5.0,
        max_output_bytes=64 * 1024,
    )


@pytest.mark.asyncio
async def test_candidate_write_success(workspace: pathlib.Path, context: ToolExecutionContext):
    executor = CandidateSafeToolExecutor()
    assert executor.allowed_tools == frozenset(["Write"])

    invocation = ToolInvocation(
        invocation_id="inv-1",
        name="Write",
        arguments={"path": "output.txt", "content": "hello world"},
    )
    executor.validate_arguments(invocation, context=context)

    result = await executor.execute(invocation, context=context)
    assert result.exit_code == 0
    assert result.stderr == ""
    assert "successfully wrote" in result.stdout

    written_file = workspace / "output.txt"
    assert written_file.is_file()
    assert written_file.read_text(encoding="utf-8") == "hello world"


@pytest.mark.asyncio
async def test_candidate_rejects_unknown_tool(workspace: pathlib.Path, context: ToolExecutionContext):
    executor = CandidateSafeToolExecutor()
    invocation = ToolInvocation(
        invocation_id="inv-2",
        name="Read",
        arguments={"path": "output.txt", "content": ""},
    )
    with pytest.raises(ValueError, match="is not allowed"):
        executor.validate_arguments(invocation, context=context)


@pytest.mark.asyncio
async def test_candidate_rejects_invalid_arguments(workspace: pathlib.Path, context: ToolExecutionContext):
    executor = CandidateSafeToolExecutor()
    # Missing content
    with pytest.raises(ValueError, match="missing required arguments"):
        executor.validate_arguments(
            ToolInvocation(invocation_id="3", name="Write", arguments={"path": "a.txt"}),
            context=context,
        )
    # Extra argument
    with pytest.raises(ValueError, match="unsupported arguments"):
        executor.validate_arguments(
            ToolInvocation(
                invocation_id="4",
                name="Write",
                arguments={"path": "a.txt", "content": "x", "bad": "y"},
            ),
            context=context,
        )


@pytest.mark.asyncio
async def test_candidate_rejects_path_traversal(workspace: pathlib.Path, context: ToolExecutionContext):
    executor = CandidateSafeToolExecutor()
    invocation = ToolInvocation(
        invocation_id="inv-5",
        name="Write",
        arguments={"path": "../escape.txt", "content": "malicious"},
    )
    executor.validate_arguments(invocation, context=context)
    result = await executor.execute(invocation, context=context)
    assert result.exit_code != 0
    assert "traversal" in result.stderr
    assert not (workspace.parent / "escape.txt").exists()


@pytest.mark.asyncio
async def test_candidate_rejects_existing_file_overwrite(workspace: pathlib.Path, context: ToolExecutionContext):
    executor = CandidateSafeToolExecutor()
    existing = workspace / "exists.txt"
    existing.write_text("original")

    invocation = ToolInvocation(
        invocation_id="inv-6",
        name="Write",
        arguments={"path": "exists.txt", "content": "new content"},
    )
    result = await executor.execute(invocation, context=context)
    assert result.exit_code != 0
    assert "already exists" in result.stderr
    assert existing.read_text(encoding="utf-8") == "original"


@pytest.mark.asyncio
async def test_candidate_respects_max_output_bytes(workspace: pathlib.Path, context: ToolExecutionContext):
    executor = CandidateSafeToolExecutor()
    small_context = ToolExecutionContext(
        workspace_root=workspace,
        timeout_seconds=5.0,
        max_output_bytes=5,
    )
    invocation = ToolInvocation(
        invocation_id="inv-7",
        name="Write",
        arguments={"path": "long.txt", "content": "toolongcontent"},
    )
    result = await executor.execute(invocation, context=small_context)
    assert result.exit_code != 0
    assert "max_output_bytes" in result.stderr
