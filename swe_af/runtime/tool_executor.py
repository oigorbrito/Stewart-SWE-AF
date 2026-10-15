"""Contract for a future sandboxed harness-tool executor.

There is intentionally no concrete implementation in SWE-AF: provider CLIs
currently receive tool names and apply provider-specific permissions. This
Protocol is a contract for an independently reviewed executor, not a sandbox.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol


ToolName = Literal["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
TOOL_NAMES: frozenset[str] = frozenset(
    {"Read", "Write", "Edit", "Bash", "Glob", "Grep"}
)


@dataclass(frozen=True)
class ToolInvocation:
    """One validated provider tool call, with a stable ID for audit records."""

    invocation_id: str
    name: ToolName
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class ToolExecutionContext:
    """Hard limits an executor must enforce for one invocation."""

    workspace_root: Path
    timeout_seconds: float
    max_output_bytes: int


@dataclass(frozen=True)
class ToolExecutionResult:
    """Bounded result returned by an executor."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False


class SafeToolExecutor(Protocol):
    """Required contract; implementations must be sandboxed and independently reviewed.

    ``allowed_tools`` is an explicit allowlist. ``validate_arguments`` must
    reject unknown/missing arguments before side effects. ``execute`` must
    canonicalize and confine all paths to ``workspace_root``, enforce timeout
    and output limits, and propagate ``asyncio.CancelledError`` while stopping
    the underlying process. Bash is not safe by default: it may be allowed only
    when backed by a separately reviewed OS/container sandbox.
    """

    @property
    def allowed_tools(self) -> frozenset[ToolName]: ...

    def validate_arguments(
        self,
        invocation: ToolInvocation,
        *,
        context: ToolExecutionContext,
    ) -> None: ...

    async def execute(
        self,
        invocation: ToolInvocation,
        *,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult: ...
