"""Sandboxed Docker tool executor for SWE-AF.

Executes tools inside an isolated, disposable Docker container with:
- --network none (no network connectivity)
- --read-only (immutable root filesystem)
- --cap-drop ALL (no Linux capabilities)
- --security-opt no-new-privileges (privilege escalation blocked)
- --pids-limit 64, --memory 128m, --cpus 1 (bounded resources)
- --user 65534:65534 (unprivileged nobody user)
- --tmpfs /tmp:rw,noexec,nosuid,size=16m (ephemeral in-memory tmpfs)
- No host bind mounts, Docker socket mounts, or credentials
- Pinned image digest (python@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4)
- Stdin JSON protocol (no user content in argv, code, or flags)
- Bounded stdout/stderr stream reading during execution
- Guaranteed container cleanup by unique name on completion, timeout, or cancellation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import json
import re
import uuid
from typing import Any

from swe_af.runtime.tool_executor import (
    SafeToolExecutor,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolInvocation,
    ToolName,
)

# Pinned Python 3.12 Alpine image by SHA256 digest
PINNED_DOCKER_IMAGE_DIGEST = (
    "python@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4"
)
PINNED_DOCKER_IMAGE_ARCH = "amd64"
PINNED_DOCKER_IMAGE_OS = "linux"

_MAX_PATH_BYTES = 1024
_MAX_CONTENT_BYTES = 64 * 1024
_DEFAULT_MAX_OUTPUT_BYTES = 64 * 1024

_RESERVED_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
})

_FORBIDDEN_PATH_CHARS = frozenset({'*', '?', '"', '<', '>', '|', ':'})

_IN_CONTAINER_PYTHON_SCRIPT = """
import sys
import json
import os
import pathlib

_WORKSPACE_DIR = pathlib.Path("/tmp/kevin_workspace")

def main():
    try:
        raw = sys.stdin.read(131072)
        if not raw:
            sys.stderr.write("Empty payload received on stdin\\n")
            sys.exit(1)
        data = json.loads(raw)
        rel_path = data.get("path")
        content = data.get("content")
        if not isinstance(rel_path, str) or not isinstance(content, str):
            sys.stderr.write("Invalid payload format\\n")
            sys.exit(1)

        _WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        workspace_root = _WORKSPACE_DIR.resolve()
        target = (workspace_root / rel_path).resolve()

        if not target.is_relative_to(workspace_root) or target == workspace_root:
            sys.stderr.write("Path traversal outside workspace is forbidden\\n")
            sys.exit(1)

        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.parent.resolve().is_relative_to(workspace_root):
            sys.stderr.write("Parent directory traversal outside workspace is forbidden\\n")
            sys.exit(1)

        content_bytes = content.encode("utf-8")
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        fd = os.open(str(target), flags, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(content_bytes)

        with open(str(target), "rb") as f:
            verified = f.read()
        if verified != content_bytes:
            sys.stderr.write("Integrity verification failed\\n")
            sys.exit(1)

        sys.stdout.write(f"successfully wrote {len(content_bytes)} bytes to {rel_path}\\n")
        sys.exit(0)
    except FileExistsError:
        sys.stderr.write("File already exists; overwriting is forbidden\\n")
        sys.exit(1)
    except Exception as exc:
        sys.stderr.write(f"Container write execution error: {exc}\\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
"""


async def _read_stream_bounded(
    stream: asyncio.StreamReader | None,
    limit: int,
) -> tuple[bytes, bool]:
    """Read an asyncio stream in chunks up to limit bytes.
    
    Returns (captured_bytes, overflow_detected).
    If bytes exceed limit, reading stops and overflow_detected is True.
    """
    if stream is None:
        return b"", False
    chunks: list[bytes] = []
    total = 0
    overflow = False
    chunk_size = 4096

    while True:
        chunk = await stream.read(chunk_size)
        if not chunk:
            break
        if total + len(chunk) > limit:
            remaining = limit - total
            if remaining > 0:
                chunks.append(chunk[:remaining])
                total += remaining
            overflow = True
            break
        chunks.append(chunk)
        total += len(chunk)

    return b"".join(chunks), overflow


async def _force_remove_container(container_name: str) -> None:
    """Explicitly remove container by name on the host Docker daemon."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "rm", "-f", container_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except Exception:
        pass


class DockerSafeToolExecutor:
    """SafeToolExecutor implementation executing tools in disposable Docker containers."""

    def __init__(self, image_digest: str = PINNED_DOCKER_IMAGE_DIGEST) -> None:
        self._image_digest = image_digest

    @property
    def image_digest(self) -> str:
        return self._image_digest

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

        path_bytes = path_arg.encode("utf-8")
        if len(path_bytes) > _MAX_PATH_BYTES:
            raise ValueError(f"path argument exceeds byte limit ({_MAX_PATH_BYTES} bytes)")

        content_bytes = content_arg.encode("utf-8")
        if len(content_bytes) > _MAX_CONTENT_BYTES:
            raise ValueError(f"content argument exceeds byte limit ({_MAX_CONTENT_BYTES} bytes)")

        if len(content_bytes) > context.max_output_bytes:
            raise ValueError("content exceeds context max_output_bytes")

        # Rejection of NUL characters
        if "\0" in path_arg:
            raise ValueError("path argument contains forbidden NUL character")

        # Rejection of Windows backslashes (container is Linux POSIX)
        if "\\" in path_arg:
            raise ValueError("path argument contains incompatible Windows separator '\\'; only POSIX '/' is allowed")

        # Rejection of absolute paths (POSIX, Windows drive, or UNC)
        if (
            path_arg.startswith("/")
            or bool(re.match(r"^[a-zA-Z]:", path_arg))
            or path_arg.startswith("//")
        ):
            raise ValueError("absolute path is forbidden")

        # Rejection of directory traversal and invalid path segments
        segments = path_arg.split("/")
        for segment in segments:
            if segment in ("", ".", ".."):
                raise ValueError("path traversal or empty path segment is forbidden")
            # Check forbidden path characters
            if any(ch in _FORBIDDEN_PATH_CHARS for ch in segment):
                raise ValueError(f"path segment {segment!r} contains forbidden character")
            # Check reserved names
            stem = segment.split(".")[0].upper()
            if stem in _RESERVED_NAMES:
                raise ValueError(f"path segment {segment!r} uses reserved name {stem!r}")

    async def execute(
        self,
        invocation: ToolInvocation,
        *,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        if asyncio.current_task() and asyncio.current_task().cancelling():
            raise asyncio.CancelledError()

        self.validate_arguments(invocation, context=context)

        path_arg = invocation.arguments["path"]
        content_arg = invocation.arguments["content"]
        payload_bytes = json.dumps({"path": path_arg, "content": content_arg}).encode("utf-8")

        container_name = f"kevin-tool-{uuid.uuid4().hex[:16]}"

        docker_cmd = [
            "docker", "run",
            "--rm",
            "--name", container_name,
            "--network", "none",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", "64",
            "--memory", "128m",
            "--cpus", "1",
            "--user", "65534:65534",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
            "--workdir", "/tmp",
            "-i",
            self.image_digest,
            "python", "-u", "-c", _IN_CONTAINER_PYTHON_SCRIPT,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            return ToolExecutionResult(
                stderr=f"Docker command failed: executable not found ({exc})",
                exit_code=1,
            )
        except Exception as exc:
            return ToolExecutionResult(
                stderr=f"Docker execution failed: {exc}",
                exit_code=1,
            )

        stdout_data = b""
        stderr_data = b""
        overflow_occurred = False
        timed_out = False

        async def _run_io() -> None:
            nonlocal stdout_data, stderr_data, overflow_occurred
            if proc.stdin:
                try:
                    proc.stdin.write(payload_bytes)
                    await proc.stdin.drain()
                    proc.stdin.close()
                    await proc.stdin.wait_closed()
                except Exception:
                    pass

            stdout_task = asyncio.create_task(
                _read_stream_bounded(proc.stdout, context.max_output_bytes)
            )
            stderr_task = asyncio.create_task(
                _read_stream_bounded(proc.stderr, context.max_output_bytes)
            )

            (stdout_data, stdout_overflow), (stderr_data, stderr_overflow) = await asyncio.gather(
                stdout_task, stderr_task
            )
            if stdout_overflow or stderr_overflow:
                overflow_occurred = True

            await proc.wait()

        try:
            await asyncio.wait_for(_run_io(), timeout=context.timeout_seconds)
        except asyncio.TimeoutError:
            timed_out = True
        except asyncio.CancelledError:
            raise
        finally:
            if proc.returncode is None:
                try:
                    proc.kill()
                except OSError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except Exception:
                    pass
            # Force removal to avoid orphan containers on host Docker daemon
            await _force_remove_container(container_name)

        if timed_out:
            return ToolExecutionResult(
                stderr=f"Docker tool execution timed out after {context.timeout_seconds} seconds",
                exit_code=1,
                timed_out=True,
            )

        if overflow_occurred:
            return ToolExecutionResult(
                stderr=f"Docker output exceeded maximum allowed bytes ({context.max_output_bytes})",
                exit_code=1,
            )

        stdout_str = stdout_data.decode("utf-8", errors="replace")
        stderr_str = stderr_data.decode("utf-8", errors="replace")

        return ToolExecutionResult(
            stdout=stdout_str,
            stderr=stderr_str,
            exit_code=proc.returncode if proc.returncode is not None else 1,
            timed_out=False,
        )
