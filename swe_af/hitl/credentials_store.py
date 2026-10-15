"""Process-local, execution-scoped store for credentials the scout negotiates.

Why a module-level dict instead of ``BuildConfig`` or ``app.memory``:

* ``BuildConfig`` is serialized through ``to_execution_config_dict()`` and
  passed to ``execute()`` via ``app.call``. The control plane logs all
  ``app.call`` input data, which would persist the credentials.
* ``app.memory`` (scope=``run``) is synced to the control plane DB by design
  — also persists.
* Filesystem under ``artifacts_dir`` is written to disk and archived.

The scout's negotiation produces credentials that should *only* live in the
agent process's memory for the duration of the build, then be cleared. A
module-level dict keyed by execution_id is the simplest way to achieve that
while keeping concurrent builds (which share the Python process) isolated.

Security boundary:

* Values are never logged.
* Values are never written to disk.
* Values are not serialized through ``app.call`` (use this store from inside
  the receiving reasoner, not as a kwarg).
* The build()'s ``finally`` block MUST call ``clear_scoped_credentials`` —
  every error path included.
"""

from __future__ import annotations

import threading

# Module-level. Keyed by execution_id (each build has its own).
_STORE: dict[str, dict[str, str]] = {}
_LOCK = threading.Lock()


def store_scoped_credentials(execution_id: str, creds: dict[str, str]) -> None:
    """Replace the stored credentials for ``execution_id`` with ``creds``.

    Filters out None/empty values so a partially-filled mega-form (user skipped
    some fields) doesn't surface as empty env vars to downstream subprocesses
    (which can be confusing — "is the env set or not?").
    """
    if not execution_id:
        return
    filtered = {
        k: v
        for k, v in (creds or {}).items()
        if isinstance(v, str) and v.strip()
    }
    with _LOCK:
        if filtered:
            _STORE[execution_id] = filtered
        else:
            _STORE.pop(execution_id, None)


def get_scoped_credentials(execution_id: str) -> dict[str, str]:
    """Return a *copy* of the stored credentials for ``execution_id``.

    Returns an empty dict if nothing is stored — callers should treat that as
    "no credentials negotiated; rely on os.environ only".
    """
    if not execution_id:
        return {}
    with _LOCK:
        stored = _STORE.get(execution_id)
        return dict(stored) if stored else {}


def clear_scoped_credentials(execution_id: str) -> None:
    """Remove credentials for ``execution_id`` from process memory."""
    if not execution_id:
        return
    with _LOCK:
        _STORE.pop(execution_id, None)


def inject_credentials_into_env(
    base_env: dict[str, str] | None, execution_id: str
) -> dict[str, str]:
    """Return a NEW env dict = ``base_env`` ∪ scoped credentials.

    Scoped credentials WIN over ``base_env`` so a freshly-minted token from
    the scout overrides any stale value already in os.environ (e.g. an
    expired RAILWAY_TOKEN from a previous build).

    Callers should use this immediately before each harness dispatch,
    passing the result as the ``env=`` kwarg. The base is normally
    ``dict(os.environ)`` so the subprocess still inherits everything the
    parent has — we only ADD/override the scoped creds.
    """
    merged: dict[str, str] = dict(base_env or {})
    creds = get_scoped_credentials(execution_id)
    if creds:
        merged.update(creds)
    return merged
