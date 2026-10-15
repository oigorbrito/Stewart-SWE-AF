"""Candidate implementation of SafeToolExecutor for review.

Supports a single Write tool restricted to a controlled temporary workspace.
This candidate is not registered in the dispatcher and remains inactive
unless explicitly instantiated and reviewed.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
from collections.abc import Mapping
from typing import Any

from swe_af.runtime.tool_executor import (
    ToolExecutionContext,
    ToolExecutionResult,
    ToolInvocation,
    ToolName,
)

_MAX_ARG_BYTES = 16 * 1024
_MAX_CONTENT_BYTES = 64 * 1024
_MAX_OUTPUT_BYTES = 64 * 1024


class CandidateSafeToolExecutor:
    """A concrete SafeToolExecutor candidate supporting only the 'Write' tool.

    Enforces workspace confinement via path resolution, exclusive creation,
    explicit argument validation, and strict size limits.
    """

    @property
    def allowed_tools(self) -> frozenset[ToolName]:
        return frozenset(["Write"])

    def validate_arguments(
        self,
        invocation: ToolInvocation,
        *,
        context: ToolExecutionContext,
    ) -> None:
        if invocation.name != "Write":
            raise ValueError(f"tool {invocation.name!r} is not allowed")

        if not isinstance(invocation.arguments, Mapping):
            raise ValueError("tool arguments must be a mapping")

        # Reject unknown arguments
        allowed_keys = {"path", "content"}
        unknown_keys = set(invocation.arguments.keys()).difference(allowed_keys)
        if unknown_keys:
            raise ValueError(f"unsupported arguments: {', '.join(sorted(unknown_keys))}")

        missing_keys = allowed_keys.difference(invocation.arguments.keys())
        if missing_keys:
            raise ValueError(f"missing required arguments: {', '.join(sorted(missing_keys))}")

        path_arg = invocation.arguments.get("path")
        content_arg = invocation.arguments.get("content")

        if not isinstance(path_arg, str) or not path_arg.strip():
            raise ValueError("path argument must be a non-empty string")
        if not isinstance(content_arg, str):
            raise ValueError("content argument must be a string")

        if len(path_arg.encode("utf-8")) > _MAX_ARG_BYTES:
            raise ValueError("path argument exceeds byte limit")
        if len(content_arg.encode("utf-8")) > _MAX_CONTENT_BYTES:
            raise ValueError("content argument exceeds byte limit")

    async def execute(
        self,
        invocation: ToolInvocation,
        *,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        # Check cancellation before execution
        if asyncio.current_task() and asyncio.current_task().cancelling():
            raise asyncio.CancelledError()

        self.validate_arguments(invocation, context=context)

        workspace_root = pathlib.Path(context.workspace_root).resolve()
        if not workspace_root.is_dir():
            return ToolExecutionResult(
                stderr="workspace root is not a valid directory",
                exit_code=1,
            )

        raw_path = invocation.arguments["path"]
        content = invocation.arguments["content"]

        # Prevent absolute paths or directory traversal escaping workspace
        try:
            target_path = (workspace_root / raw_path).resolve()
        except Exception as exc:
            return ToolExecutionResult(
                stderr=f"path resolution failed: {exc}",
                exit_code=1,
            )
        try:
            # Ensure target_path is within workspace_root
            target_path.relative_to(workspace_root.resolve())
        except ValueError:
            return ToolExecutionResult(
                stderr="path traversal outside workspace is forbidden",
                exit_code=1,
            )

        if target_path == workspace_root:
            return ToolExecutionResult(
                stderr="cannot write to workspace root directory itself",
                exit_code=1,
            )

        # Ensure parent directory exists within workspace
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            parent_resolved = target_path.parent.resolve()
            # Ensure parent is within workspace
            parent_resolved.relative_to(workspace_root.resolve())
        except Exception as exc:
            return ToolExecutionResult(
                stderr=f"failed to create parent directories: {exc}",
                exit_code=1,
            )

        # Execute write with exclusive creation (O_CREAT | O_EXCL) to prevent overwriting
        content_bytes = content.encode("utf-8")
        if len(content_bytes) > context.max_output_bytes:
            return ToolExecutionResult(
                stderr="content exceeds context max_output_bytes",
                exit_code=1,
            )

        try:
            # os.open with O_CREAT | O_EXCL provides atomic exclusive creation
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY

            fd = os.open(str(target_path), flags, 0o600)
            try:
                with os.fdopen(fd, "wb", closefd=True) as f:
                    f.write(content_bytes)
            except Exception:
                # If fdopen failed without taking ownership, ensure fd is closed
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise
        except FileExistsError:
            return ToolExecutionResult(
                stderr="file already exists; overwriting is forbidden",
                exit_code=1,
            )
        except OSError as exc:
            return ToolExecutionResult(
                stderr=f"file system write error: {exc}",
                exit_code=1,
            )
        except Exception as exc:
            return ToolExecutionResult(
                stderr=f"unexpected write error: {exc}",
                exit_code=1,
            )

        return ToolExecutionResult(
            stdout=f"successfully wrote {len(content_bytes)} bytes to {raw_path}",
            exit_code=0,
        )