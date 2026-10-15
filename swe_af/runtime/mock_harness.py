"""Deterministic, local-only fixtures for one real SWE-AF harness path.

This backend is not a model, transport, provider emulator, or cost/usage
source. It is intentionally limited to FastPlanResult and rejects tools and
unknown schemas so it cannot masquerade as general AgentField compatibility.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from swe_af.fast.schemas import FastPlanResult
from swe_af.runtime.application_harness import (
    HarnessAgent,
    HarnessRequest,
    register_backend,
)

MOCK_BACKEND = "local-mock"
_MAX_PROMPT_BYTES = 64 * 1024
_MAX_FIXTURE_BYTES = 64 * 1024


class MockHarnessError(RuntimeError):
    """The local fixture cannot satisfy the requested harness contract."""


@dataclass(frozen=True)
class MockHarnessResult:
    result: str
    parsed: BaseModel
    is_error: bool = False
    error_message: str | None = None
    failure_type: str = "none"
    cost_usd: None = None
    num_turns: int = 1
    duration_ms: int = 0
    session_id: str = "local-mock"
    messages: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    total_tokens: int = 0
    model: str = "local-fixture"


_FIXTURES: dict[type[BaseModel], dict[str, Any]] = {
    FastPlanResult: {
        "tasks": [
            {
                "name": "fixture-task",
                "title": "Local fixture task",
                "description": "Deterministic mock output; no model inference occurred.",
                "acceptance_criteria": ["Fixture is parsed by the requested schema."],
                "files_to_create": [],
                "files_to_modify": [],
                "estimated_minutes": 5,
            }
        ],
        "rationale": "Deterministic local fixture; no model inference occurred.",
        "fallback_used": False,
    }
}


async def _mock_handler(
    _agent: HarnessAgent, request: HarnessRequest
) -> MockHarnessResult:
    prompt_bytes = request.prompt.encode("utf-8")
    if len(prompt_bytes) > _MAX_PROMPT_BYTES:
        raise MockHarnessError("local mock prompt exceeds byte limit")
    tools = request.options.get("tools")
    if tools:
        raise MockHarnessError("local mock does not execute or emulate tools")
    schema = request.options.get("schema")
    if schema not in _FIXTURES:
        raise MockHarnessError("local mock has no fixture for the requested schema")
    try:
        parsed = schema.model_validate(_FIXTURES[schema])
        serialized = json.dumps(parsed.model_dump(mode="json"), separators=(",", ":"))
    except Exception as exc:
        raise MockHarnessError("local mock fixture failed schema validation") from exc
    if len(serialized.encode("utf-8")) > _MAX_FIXTURE_BYTES:
        raise MockHarnessError("local mock fixture exceeds byte limit")
    return MockHarnessResult(result=serialized, parsed=parsed)


def register_local_mock() -> None:
    """Register the fixture in the application-owned dispatch registry."""
    register_backend(MOCK_BACKEND, _mock_handler)
