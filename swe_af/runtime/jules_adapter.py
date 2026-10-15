"""Jules remote agent adapter for Stewart-SWE-AF.
Uses JULES_API_KEY from env only; never logs it.
No calls during import/init.
"""
import os, json, re, urllib.request, urllib.error
from typing import Any, Dict, Optional


_SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+", re.IGNORECASE),
    re.compile(r"(?:api[_-]?key|token|secret|password|auth|authorization)\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.]+['\"]?", re.IGNORECASE),
    re.compile(r"AIza[A-Za-z0-9_\-]{30,}"),
    re.compile(r"(?:sk-[A-Za-z0-9_\-]{20,}|gh[pousr]_[A-Za-z0-9_\-]{20,})"),
]


def _scrub_text(text: Any, api_key: Optional[str] = None) -> str:
    if text is None:
        return ""
    scrubbed = str(text)
    if api_key and len(api_key.strip()) >= 4:
        scrubbed = scrubbed.replace(api_key.strip(), "[REDACTED]")
    for pattern in _SECRET_PATTERNS:
        scrubbed = pattern.sub("[REDACTED]", scrubbed)
    # Collapse newlines, carriage returns, and tabs to prevent log injection
    scrubbed = re.sub(r"[\r\n\t]+", " ", scrubbed).strip()
    if len(scrubbed) > 512:
        scrubbed = scrubbed[:509] + "..."
    return scrubbed


class JulesAdapter:
    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0):
        self.api_key = api_key or os.environ.get("JULES_API_KEY")
        self.timeout = timeout
        self.base = "https://jules.googleapis.com/v1alpha"

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise RuntimeError("JULES_API_KEY missing")
        return {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    def _sanitize_error(
        self,
        exc: Exception,
        method: str = "REQUEST",
        path: str = "",
    ) -> RuntimeError:
        """Sanitize network and HTTP errors, logging method, relative path, and API message without secrets."""
        rel_path = path
        if self.base in rel_path:
            rel_path = rel_path.split(self.base, 1)[-1]
        rel_path = rel_path.split("?")[0]  # strip any query string
        rel_path = _scrub_text(rel_path, self.api_key)

        if isinstance(exc, urllib.error.HTTPError):
            reason_val = getattr(exc, "reason", None) or getattr(exc, "msg", "")
            reason_str = _scrub_text(reason_val, self.api_key)
            detail_msg = None
            try:
                raw_body = exc.read(8192).decode("utf-8", errors="ignore")
                if raw_body:
                    body_json = json.loads(raw_body)
                    if isinstance(body_json, dict) and "error" in body_json:
                        err_obj = body_json["error"]
                        if isinstance(err_obj, dict):
                            detail_msg = err_obj.get("message")
                        elif isinstance(err_obj, str):
                            detail_msg = err_obj
            except Exception:
                detail_msg = None

            if detail_msg:
                clean_detail = _scrub_text(detail_msg, self.api_key)
                if clean_detail:
                    return RuntimeError(
                        f"Jules API {method} {rel_path} HTTP error {exc.code} ({reason_str}): {clean_detail}"
                    )
            return RuntimeError(
                f"Jules API {method} {rel_path} HTTP error {exc.code}: {reason_str}"
            )
        if isinstance(exc, urllib.error.URLError):
            reason_str = _scrub_text(getattr(exc, "reason", str(exc)), self.api_key)
            return RuntimeError(f"Jules API {method} {rel_path} connection error: {reason_str}")
        return RuntimeError(f"Jules API {method} {rel_path} error: {type(exc).__name__}")

    def create_session(
        self,
        prompt: str,
        require_plan_approval: bool = True,
        **extra_options: Any,
    ) -> Dict[str, Any]:
        """Creates a Jules session with isolated single invocation and optional requirePlanApproval."""
        if not self.api_key:
            raise RuntimeError("JULES_API_KEY missing")

        payload: Dict[str, Any] = {
            "prompt": prompt,
            "requirePlanApproval": require_plan_approval,
        }
        for k, v in extra_options.items():
            if v is not None:
                payload[k] = v

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/sessions",
            data=data,
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            raise self._sanitize_error(exc, method="POST", path="/sessions") from None
        except Exception as exc:
            raise self._sanitize_error(exc, method="POST", path="/sessions") from None

    def get_status(self, session_id: str) -> Dict[str, Any]:
        """Retrieves session status/state via official GET /sessions/{session_id}."""
        if not self.api_key:
            raise RuntimeError("JULES_API_KEY missing")
        name = session_id if session_id.startswith("sessions/") else f"sessions/{session_id}"
        req_path = f"/{name}"
        req = urllib.request.Request(
            f"{self.base}{req_path}",
            headers=self._headers(),
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            raise self._sanitize_error(exc, method="GET", path=req_path) from None
        except Exception as exc:
            raise self._sanitize_error(exc, method="GET", path=req_path) from None

    def get_result(self, session_id: str) -> Dict[str, Any]:
        """Retrieves session activities/results via official GET /sessions/{session_id}/activities."""
        if not self.api_key:
            raise RuntimeError("JULES_API_KEY missing")
        name = session_id if session_id.startswith("sessions/") else f"sessions/{session_id}"
        req_path = f"/{name}/activities"
        req = urllib.request.Request(
            f"{self.base}{req_path}",
            headers=self._headers(),
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            raise self._sanitize_error(exc, method="GET", path=req_path) from None
        except Exception as exc:
            raise self._sanitize_error(exc, method="GET", path=req_path) from None


# Harness integration: register Jules backend locally
from .application_harness import register_backend, HarnessAgent, HarnessRequest
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import threading
from types import SimpleNamespace


_AUDIT_LOCK = threading.Lock()
AUDIT_LOG_PATH = Path("logs") / "jules_operational_audit.jsonl"


def _persist_session_audit(session_id: str, outcome: str = "created", log_path: Optional[Path] = None) -> None:
    """Safely persist minimal operational metadata for a created session.

    Logs ONLY UTC timestamp, session identifier, outcome, and schema version.
    Never logs prompts, API keys, headers, or full response bodies.
    """
    path = log_path or AUDIT_LOG_PATH
    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "event": "session_created",
        "outcome": outcome,
        "version": "1.0",
    }
    line = json.dumps(record, separators=(",", ":")) + "\n"

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_LOCK:
            # Create file with restricted user-only permissions if supported
            if not path.exists():
                path.touch(mode=0o600, exist_ok=True)
            try:
                os.chmod(path, 0o600)
            except (OSError, NotImplementedError):
                pass
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
    except Exception as exc:
        raise RuntimeError(
            "Jules session created successfully but operational audit persistence failed; "
            "session retained in memory"
        ) from exc


TERMINAL_SUCCESS_STATES = {"COMPLETED", "SUCCEEDED"}
TERMINAL_FAILURE_STATES = {"FAILED", "CANCELLED", "CANCELED"}
TERMINAL_STATES = TERMINAL_SUCCESS_STATES | TERMINAL_FAILURE_STATES


class JulesHarnessAgent:
    def __init__(self, audit_path: Optional[Path] = None):
        self.audit_path = audit_path

    async def harness(self, prompt: str, **options: Any) -> Any:
        import time

        adapter = JulesAdapter()
        require_plan_approval = options.get("require_plan_approval", True)
        # Execute network creation off the asyncio event loop thread
        session = await asyncio.to_thread(
            adapter.create_session, prompt, require_plan_approval=require_plan_approval
        )
        session_id = session.get("id") or session.get("name")

        # Step 1: Guarantee persistence of session identifier immediately after creation
        audit_error = None
        if session_id:
            try:
                _persist_session_audit(str(session_id), outcome="created", log_path=self.audit_path)
            except Exception as exc:
                audit_error = str(exc)

        # Step 2: Query follow-up status and activities only if audit succeeded and not skipped
        skip_queries = options.get("skip_status_and_result", False) or bool(audit_error)
        wait_for_completion = options.get("wait_for_completion", True)
        poll_interval = float(options.get("poll_interval", os.environ.get("JULES_POLL_INTERVAL", "1.0")))
        poll_timeout = float(
            options.get("timeout_seconds")
            or options.get("poll_timeout", os.environ.get("JULES_POLL_TIMEOUT", "300.0"))
        )

        status: Dict[str, Any] = {}
        result: Dict[str, Any] = {}
        timed_out = False
        start_time = time.monotonic()
        deadline = start_time + poll_timeout

        if not skip_queries and session_id:
            while True:
                try:
                    # Non-blocking async status query
                    status = await asyncio.to_thread(adapter.get_status, session_id)
                except Exception as exc:
                    status = {"unconfirmed": True, "error": str(exc), "state": "UNCONFIRMED"}

                state_str = str(
                    status.get("state")
                    or session.get("state")
                    or session.get("status")
                    or "UNKNOWN"
                ).upper()

                if state_str in TERMINAL_STATES:
                    break

                if not wait_for_completion:
                    break

                if status.get("unconfirmed"):
                    # Immediately interrupt remote flow when status query fails
                    break

                now = time.monotonic()
                if now >= deadline:
                    timed_out = True
                    break

                remaining = deadline - now
                sleep_dur = min(poll_interval, remaining)
                if sleep_dur > 0:
                    await asyncio.sleep(sleep_dur)
                else:
                    timed_out = True
                    break

            # Fetch activities / results once terminal or requested
            # Halts without calling the remote activities endpoint if status query failed
            if status.get("unconfirmed"):
                result = {"unconfirmed": True, "activities": []}
            elif state_str in TERMINAL_STATES or not wait_for_completion:
                try:
                    # Non-blocking async result query
                    result = await asyncio.to_thread(adapter.get_result, session_id)
                except Exception as exc:
                    result = {"unconfirmed": True, "error": str(exc), "activities": []}
            elif timed_out:
                result = {"timeout": True, "activities": []}
            else:
                result = {"activities": [], "in_progress": True}
        else:
            if audit_error:
                status = {"state": "AUDIT_FAILED", "queried": False, "audit_failure": True}
                result = {"queried": False, "activities": []}
            else:
                status = {"state": session.get("state") or session.get("status") or "QUEUED", "queried": False}
                result = {"queried": False}

        state_str = str(
            status.get("state")
            or session.get("state")
            or session.get("status")
            or "QUEUED"
        ).upper()

        # Step 3: Determine outcome, errors, and terminal completion
        error_message: Optional[str] = None
        failure_type = "none"

        if audit_error:
            error_message = audit_error
            failure_type = "audit_persistence_failure"
        elif timed_out:
            error_message = f"Jules session {session_id} timed out after {poll_timeout}s in state {state_str}"
            failure_type = "timeout"
        elif state_str in TERMINAL_FAILURE_STATES:
            error_message = f"Jules session {session_id} ended with state {state_str}"
            failure_type = "session_failed"
        elif status.get("unconfirmed") and status.get("error"):
            error_message = status.get("error")
            failure_type = "status_query_error"

        is_error = bool(error_message)
        complete = (state_str in TERMINAL_SUCCESS_STATES) and not is_error

        # Extract changed files from activities if present
        files_changed: list[str] = []
        activities = result.get("activities", []) if isinstance(result, dict) else []
        if isinstance(activities, list):
            for act in activities:
                if isinstance(act, dict):
                    if "files_changed" in act and isinstance(act["files_changed"], list):
                        files_changed.extend(str(f) for f in act["files_changed"])
                    elif "file" in act and isinstance(act["file"], str):
                        files_changed.append(act["file"])
                    elif "artifacts" in act and isinstance(act["artifacts"], list):
                        for art in act["artifacts"]:
                            if isinstance(art, dict) and "path" in art:
                                files_changed.append(str(art["path"]))
        seen = set()
        files_changed = [f for f in files_changed if not (f in seen or seen.add(f))]

        summary_parts = [f"Jules session {session_id} ({state_str})"]
        if error_message:
            summary_parts.append(f"error: {error_message}")
        summary = " - ".join(summary_parts)

        parsed_data = {
            "session_id": session_id,
            "status": status,
            "result": result,
            "session": session,
            "summary": summary,
            "complete": complete,
            "files_changed": files_changed,
        }
        if audit_error:
            parsed_data["audit_warning"] = audit_error

        raw_result_str = json.dumps(parsed_data)

        # Build schema object if a Pydantic schema was passed in options
        schema = options.get("schema")
        parsed_obj = None
        if schema is not None:
            try:
                parsed_obj = schema.model_validate(parsed_data)
            except Exception:
                parsed_obj = None

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        return SimpleNamespace(
            result=raw_result_str,
            parsed=parsed_obj or parsed_data,
            is_error=is_error,
            error_message=error_message,
            failure_type=failure_type,
            session_id=session_id,
            summary=summary,
            complete=complete,
            files_changed=files_changed,
            status=status,
            activities=result,
            cost_usd=0.0,
            num_turns=1,
            duration_ms=elapsed_ms,
            messages=[{"role": "user", "content": prompt}],
            input_tokens=len(prompt.split()),
            output_tokens=len(raw_result_str.split()),
            cache_read_tokens=0,
            cache_creation_tokens=0,
            total_tokens=len(prompt.split()) + len(raw_result_str.split()),
            model="jules",
        )


def _jules_backend_handler(agent: HarnessAgent, req: HarnessRequest) -> Any:
    return JulesHarnessAgent().harness(req.prompt, **req.options)


def register_jules() -> None:
    register_backend("jules", _jules_backend_handler)
