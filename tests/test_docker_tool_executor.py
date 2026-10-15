"""Unit tests for DockerSafeToolExecutor (no Docker Engine required)."""

from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

from swe_af.runtime.docker_tool_executor import (
    DockerSafeToolExecutor,
    PINNED_DOCKER_IMAGE_DIGEST,
    _read_stream_bounded,
)
from swe_af.runtime.tool_executor import (
    ToolExecutionContext,
    ToolExecutionResult,
    ToolInvocation,
)


@pytest.fixture
def context(tmp_path: Path) -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_root=tmp_path,
        timeout_seconds=2.0,
        max_output_bytes=64 * 1024,
    )


def test_allowed_tools_only_write():
    executor = DockerSafeToolExecutor()
    assert executor.allowed_tools == frozenset(["Write"])
    assert executor.image_digest == PINNED_DOCKER_IMAGE_DIGEST


def test_validate_arguments_write_valid(context: ToolExecutionContext):
    executor = DockerSafeToolExecutor()
    invocation = ToolInvocation(
        invocation_id="inv-1",
        name="Write",
        arguments={"path": "dir/output.txt", "content": "hello world"},
    )
    executor.validate_arguments(invocation, context=context)


def test_validate_arguments_rejects_non_write(context: ToolExecutionContext):
    executor = DockerSafeToolExecutor()
    for bad_tool in ["Bash", "Read", "Edit", "Glob", "Grep"]:
        invocation = ToolInvocation(
            invocation_id="inv-bad",
            name=bad_tool,  # type: ignore
            arguments={"path": "output.txt", "content": ""},
        )
        with pytest.raises(ValueError, match="is not allowed"):
            executor.validate_arguments(invocation, context=context)


def test_validate_arguments_missing_args(context: ToolExecutionContext):
    executor = DockerSafeToolExecutor()
    # Missing content
    with pytest.raises(ValueError, match="missing required arguments"):
        executor.validate_arguments(
            ToolInvocation(invocation_id="1", name="Write", arguments={"path": "a.txt"}),
            context=context,
        )
    # Missing path
    with pytest.raises(ValueError, match="missing required arguments"):
        executor.validate_arguments(
            ToolInvocation(invocation_id="2", name="Write", arguments={"content": "x"}),
            context=context,
        )


def test_validate_arguments_extra_args(context: ToolExecutionContext):
    executor = DockerSafeToolExecutor()
    with pytest.raises(ValueError, match="unsupported arguments"):
        executor.validate_arguments(
            ToolInvocation(
                invocation_id="3",
                name="Write",
                arguments={"path": "a.txt", "content": "x", "extra": "forbidden"},
            ),
            context=context,
        )


def test_validate_arguments_empty_or_whitespace_path(context: ToolExecutionContext):
    executor = DockerSafeToolExecutor()
    for empty_path in ["", "   ", "\t\n"]:
        with pytest.raises(ValueError, match="non-empty string"):
            executor.validate_arguments(
                ToolInvocation(
                    invocation_id="4",
                    name="Write",
                    arguments={"path": empty_path, "content": "x"},
                ),
                context=context,
            )


def test_validate_arguments_absolute_paths(context: ToolExecutionContext):
    executor = DockerSafeToolExecutor()
    # POSIX absolute
    with pytest.raises(ValueError, match="absolute path is forbidden"):
        executor.validate_arguments(
            ToolInvocation(
                invocation_id="5",
                name="Write",
                arguments={"path": "/etc/passwd", "content": "evil"},
            ),
            context=context,
        )
    # Windows drive
    with pytest.raises(ValueError, match="absolute path is forbidden"):
        executor.validate_arguments(
            ToolInvocation(
                invocation_id="6",
                name="Write",
                arguments={"path": "C:/Windows/win.ini", "content": "evil"},
            ),
            context=context,
        )
    # Windows UNC
    with pytest.raises(ValueError, match="absolute path is forbidden"):
        executor.validate_arguments(
            ToolInvocation(
                invocation_id="7",
                name="Write",
                arguments={"path": "//server/share/file.txt", "content": "evil"},
            ),
            context=context,
        )


def test_validate_arguments_path_traversal(context: ToolExecutionContext):
    executor = DockerSafeToolExecutor()
    traversal_cases = [
        "../escape.txt",
        "subdir/../../escape.txt",
        "./file.txt",
        "subdir/./file.txt",
        "foo//bar.txt",
    ]
    for bad_path in traversal_cases:
        with pytest.raises(ValueError, match="path traversal or empty path segment"):
            executor.validate_arguments(
                ToolInvocation(
                    invocation_id="8",
                    name="Write",
                    arguments={"path": bad_path, "content": "evil"},
                ),
                context=context,
            )


def test_validate_arguments_windows_separators(context: ToolExecutionContext):
    executor = DockerSafeToolExecutor()
    with pytest.raises(ValueError, match="incompatible Windows separator"):
        executor.validate_arguments(
            ToolInvocation(
                invocation_id="9",
                name="Write",
                arguments={"path": r"sub\file.txt", "content": "content"},
            ),
            context=context,
        )


def test_validate_arguments_nul_character(context: ToolExecutionContext):
    executor = DockerSafeToolExecutor()
    with pytest.raises(ValueError, match="forbidden NUL character"):
        executor.validate_arguments(
            ToolInvocation(
                invocation_id="10",
                name="Write",
                arguments={"path": "file\0.txt", "content": "content"},
            ),
            context=context,
        )


def test_validate_arguments_reserved_names(context: ToolExecutionContext):
    executor = DockerSafeToolExecutor()
    for name in ["CON.txt", "con", "prn.log", "aux", "NUL.dat", "com1", "lpt2.txt"]:
        with pytest.raises(ValueError, match="reserved name"):
            executor.validate_arguments(
                ToolInvocation(
                    invocation_id="11",
                    name="Write",
                    arguments={"path": f"subdir/{name}", "content": "content"},
                ),
                context=context,
            )


def test_validate_arguments_forbidden_characters(context: ToolExecutionContext):
    executor = DockerSafeToolExecutor()
    for ch in ['*', '?', '"', '<', '>', '|', ':']:
        with pytest.raises(ValueError, match="forbidden character"):
            executor.validate_arguments(
                ToolInvocation(
                    invocation_id="12",
                    name="Write",
                    arguments={"path": f"sub{ch}dir/file.txt", "content": "content"},
                ),
                context=context,
            )


def test_validate_arguments_excessive_content(context: ToolExecutionContext):
    executor = DockerSafeToolExecutor()
    oversized = "a" * (64 * 1024 + 1)
    with pytest.raises(ValueError, match="content argument exceeds byte limit"):
        executor.validate_arguments(
            ToolInvocation(
                invocation_id="13",
                name="Write",
                arguments={"path": "file.txt", "content": oversized},
            ),
            context=context,
        )


def test_validate_arguments_content_exceeds_context_limit(tmp_path: Path):
    executor = DockerSafeToolExecutor()
    small_context = ToolExecutionContext(
        workspace_root=tmp_path,
        timeout_seconds=2.0,
        max_output_bytes=10,
    )
    with pytest.raises(ValueError, match="content exceeds context max_output_bytes"):
        executor.validate_arguments(
            ToolInvocation(
                invocation_id="14",
                name="Write",
                arguments={"path": "file.txt", "content": "12345678901"},
            ),
            context=small_context,
        )


@pytest.mark.asyncio
async def test_bounded_stream_reader():
    reader = asyncio.StreamReader()
    reader.feed_data(b"abc" * 10)
    reader.feed_eof()

    data, overflow = await _read_stream_bounded(reader, limit=10)
    assert len(data) == 10
    assert overflow is True

    reader2 = asyncio.StreamReader()
    reader2.feed_data(b"short")
    reader2.feed_eof()

    data2, overflow2 = await _read_stream_bounded(reader2, limit=10)
    assert data2 == b"short"
    assert overflow2 is False


@pytest.mark.asyncio
async def test_execute_docker_failure_mocked(context: ToolExecutionContext, monkeypatch):
    executor = DockerSafeToolExecutor()
    invocation = ToolInvocation(
        invocation_id="inv-fail",
        name="Write",
        arguments={"path": "test.txt", "content": "test"},
    )

    class MockProcess:
        def __init__(self):
            self.returncode = 125
            self.stdin = asyncio.StreamReader()
            self.stdout = asyncio.StreamReader()
            self.stderr = asyncio.StreamReader()
            self.stderr.feed_data(b"Docker daemon error: execution failed")
            self.stderr.feed_eof()
            self.stdout.feed_eof()

        async def wait(self):
            return self.returncode

        def kill(self):
            pass

    async def mock_create_subprocess_exec(*args, **kwargs):
        if "rm" in args:
            class DummyRm:
                async def wait(self): return 0
            return DummyRm()
        return MockProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", mock_create_subprocess_exec)

    result = await executor.execute(invocation, context=context)
    assert result.exit_code == 125
    assert "Docker daemon error" in result.stderr


@pytest.mark.asyncio
async def test_execute_docker_timeout_mocked(tmp_path: Path, monkeypatch):
    executor = DockerSafeToolExecutor()
    quick_context = ToolExecutionContext(
        workspace_root=tmp_path,
        timeout_seconds=0.1,
        max_output_bytes=1024,
    )
    invocation = ToolInvocation(
        invocation_id="inv-timeout",
        name="Write",
        arguments={"path": "test.txt", "content": "test"},
    )

    removed_containers = []

    class HangingProcess:
        def __init__(self):
            self.returncode = None
            self.stdin = asyncio.StreamReader()
            self.stdout = asyncio.StreamReader()
            self.stderr = asyncio.StreamReader()

        async def wait(self):
            await asyncio.sleep(5.0)
            self.returncode = -9
            return self.returncode

        def kill(self):
            self.returncode = -9

    async def mock_create_subprocess_exec(*args, **kwargs):
        if len(args) >= 3 and args[0] == "docker" and args[1] == "rm":
            removed_containers.append(args[3])
            class DummyRm:
                async def wait(self): return 0
            return DummyRm()
        return HangingProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", mock_create_subprocess_exec)

    result = await executor.execute(invocation, context=quick_context)
    assert result.exit_code == 1
    assert result.timed_out is True
    assert "timed out" in result.stderr
    assert len(removed_containers) == 1
    assert removed_containers[0].startswith("kevin-tool-")


@pytest.mark.asyncio
async def test_execute_docker_not_found(context: ToolExecutionContext, monkeypatch):
    executor = DockerSafeToolExecutor()
    invocation = ToolInvocation(
        invocation_id="inv-nofile",
        name="Write",
        arguments={"path": "test.txt", "content": "test"},
    )

    async def mock_create_subprocess_exec(*args, **kwargs):
        raise FileNotFoundError("docker not found on PATH")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", mock_create_subprocess_exec)

    result = await executor.execute(invocation, context=context)
    assert result.exit_code == 1
    assert "executable not found" in result.stderr


@pytest.mark.asyncio
async def test_execute_docker_excessive_output_mocked(tmp_path: Path, monkeypatch):
    executor = DockerSafeToolExecutor()
    small_context = ToolExecutionContext(
        workspace_root=tmp_path,
        timeout_seconds=2.0,
        max_output_bytes=20,
    )
    invocation = ToolInvocation(
        invocation_id="inv-overflow",
        name="Write",
        arguments={"path": "test.txt", "content": "short"},
    )

    class FloodProcess:
        def __init__(self):
            self.returncode = 0
            self.stdin = asyncio.StreamReader()
            self.stdout = asyncio.StreamReader()
            self.stderr = asyncio.StreamReader()
            self.stdout.feed_data(b"x" * 100)
            self.stdout.feed_eof()
            self.stderr.feed_eof()

        async def wait(self):
            return self.returncode

        def kill(self):
            pass

    async def mock_create_subprocess_exec(*args, **kwargs):
        if "rm" in args:
            class DummyRm:
                async def wait(self): return 0
            return DummyRm()
        return FloodProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", mock_create_subprocess_exec)

    result = await executor.execute(invocation, context=small_context)
    assert result.exit_code == 1
    assert "output exceeded maximum allowed bytes" in result.stderr
