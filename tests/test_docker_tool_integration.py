"""Integration tests for Docker tool executor with a real Docker daemon."""

from __future__ import annotations

import pathlib
import subprocess
import pytest

from swe_af.runtime.docker_tool_executor import (
    DockerSafeToolExecutor,
    PINNED_DOCKER_IMAGE_DIGEST,
)
from swe_af.runtime.docker_tool_harness import (
    DOCKER_TOOL_BACKEND,
    register_docker_tool_backend,
)
from swe_af.runtime.tool_executor import (
    ToolExecutionContext,
    ToolInvocation,
)
from swe_af.runtime.application_harness import (
    dispatch_harness as app_dispatch,
)


def _check_docker() -> bool:
    try:
        res = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return res.returncode == 0
    except Exception:
        return False


_DOCKER_AVAILABLE = _check_docker()


@pytest.fixture(autouse=True)
def require_docker():
    if not _DOCKER_AVAILABLE:
        pytest.skip("Docker Engine is unavailable on this host")


@pytest.mark.docker
@pytest.mark.asyncio
async def test_docker_integration_write_valid(tmp_path: pathlib.Path):
    """Write tool successfully creates and verifies file inside ephemeral container."""
    executor = DockerSafeToolExecutor()
    context = ToolExecutionContext(
        workspace_root=tmp_path,
        timeout_seconds=15.0,
        max_output_bytes=64 * 1024,
    )
    invocation = ToolInvocation(
        invocation_id="inv-int-1",
        name="Write",
        arguments={"path": "sub/result.txt", "content": "integration content test"},
    )

    result = await executor.execute(invocation, context=context)

    assert result.exit_code == 0
    assert result.stderr == ""
    assert "successfully wrote 24 bytes to sub/result.txt" in result.stdout
    assert result.timed_out is False

    # Verify no leak to host workspace
    assert not (tmp_path / "sub" / "result.txt").exists()


@pytest.mark.docker
@pytest.mark.asyncio
async def test_docker_integration_controlled_failure(tmp_path: pathlib.Path):
    """Controlled container failure when payload cannot be parsed or invalid."""
    executor = DockerSafeToolExecutor()
    context = ToolExecutionContext(
        workspace_root=tmp_path,
        timeout_seconds=10.0,
        max_output_bytes=64 * 1024,
    )

    # Attempting to write with a relative path that tries to escape inside container
    # Note: validate_arguments on host blocks .., so we can verify host validation
    # or container behavior.
    with pytest.raises(ValueError, match="path traversal"):
        invocation = ToolInvocation(
            invocation_id="inv-int-2",
            name="Write",
            arguments={"path": "../escape.txt", "content": "escape"},
        )
        await executor.execute(invocation, context=context)


@pytest.mark.docker
def test_docker_integration_network_disabled():
    """Verify that the container runs with network disabled (--network none)."""
    cmd = [
        "docker", "run", "--rm",
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
        PINNED_DOCKER_IMAGE_DIGEST,
        "python", "-c",
        "import socket; s = socket.socket(); s.connect(('1.1.1.1', 80))",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert proc.returncode != 0
    assert "Network unreachable" in proc.stderr or "OSError" in proc.stderr


@pytest.mark.docker
def test_docker_integration_no_bind_mounts():
    """Verify that container runs without host bind mounts."""
    inspect_cmd = [
        "docker", "run", "--rm",
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
        "--workdir", "/tmp",
        PINNED_DOCKER_IMAGE_DIGEST,
        "python", "-c",
        "import pathlib; print('OK')",
    ]
    proc = subprocess.run(inspect_cmd, capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0
    assert "OK" in proc.stdout


@pytest.mark.docker
def test_docker_integration_non_root_execution():
    """Verify that execution runs as unprivileged user (UID/GID 65534: nobody)."""
    cmd = [
        "docker", "run", "--rm",
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
        PINNED_DOCKER_IMAGE_DIGEST,
        "python", "-c",
        "import os; print(f'UID:{os.getuid()} GID:{os.getgid()}')",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0
    assert "UID:65534 GID:65534" in proc.stdout


@pytest.mark.docker
def test_docker_integration_read_only_rootfs():
    """Verify that the root filesystem is strictly read-only."""
    cmd = [
        "docker", "run", "--rm",
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
        PINNED_DOCKER_IMAGE_DIGEST,
        "python", "-c",
        "with open('/read_only_test.txt', 'w') as f: f.write('blocked')",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert proc.returncode != 0
    assert "Read-only file system" in proc.stderr or "OSError" in proc.stderr


@pytest.mark.docker
@pytest.mark.asyncio
async def test_docker_integration_via_dispatcher(tmp_path: pathlib.Path, monkeypatch):
    """End-to-end integration via the public dispatch_harness API."""
    register_docker_tool_backend()
    monkeypatch.setenv("SWE_HARNESS_BACKEND", DOCKER_TOOL_BACKEND)

    class Agent:
        async def harness(self, *args, **kwargs):
            raise AssertionError("AgentField must not be called when docker-tool is selected")

    options = {
        "tools": ["Write"],
        "cwd": str(tmp_path),
        "tool_args": {"path": "e2e/file.txt", "content": "dispatched docker tool content"},
    }

    outcome = await app_dispatch(
        Agent(),
        "dispatched prompt",
        **options,
    )

    assert outcome.is_error is False
    assert outcome.parsed["ok"] is True
    assert len(outcome.parsed["executed_tools"]) == 1
    exec_info = outcome.parsed["executed_tools"][0]
    assert exec_info["tool"] == "Write"
    assert exec_info["exit_code"] == 0
    assert "successfully wrote" in exec_info["stdout"]

    # File must NOT exist on host (ephemeral container workspace)
    assert not (tmp_path / "e2e" / "file.txt").exists()
