# Kevin container smoke — Windows

This is a deterministic Docker smoke test, **not** an autonomous SWE agent,
a hardened sandbox, or a verification of the existing runtime dispatcher.
It does not mount the host checkout, inject credentials, contact model APIs,
push branches or open pull requests.

## Run

Start Docker Desktop (Linux containers). In PowerShell, from the checkout
containing this script:

```powershell
powershell -NoProfile -File .\scripts\windows-container-smoke.ps1
```

The script checks the Docker Engine, optionally pulls `python:3.12-alpine`,
then runs a short Python write/read assertion in a disposable container.

Execution restrictions: `--network none`, `--read-only`, dropped Linux
capabilities, no-new-privileges, memory/CPU/PID limits, unprivileged UID,
a 16 MiB temporary filesystem and **no host mounts**. The Docker daemon
itself is a privileged local dependency. Image download may use network;
the running container does not. This is defense in depth, not a proof of
host isolation against container escape or kernel vulnerabilities.

## Acceptance
- Engine responds and the Linux image runs.
- Output includes `PASS: deterministic write/read` and
  `PASS: Kevin container smoke complete`.
- If the daemon is stopped, fail without reporting success.
- No modifications to the repository or local untracked files.

## Next stage
Integrate a narrowly scoped tool executor with the dispatcher, validate
path traversal, symlink, resource limits and cancellation, and separately
authorize model calls before describing Kevin as autonomously operational.
