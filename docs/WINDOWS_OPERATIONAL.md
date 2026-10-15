# Kevin — Windows local operational preflight

## Scope
This first step is **read-only**. It does not start containers, install packages,
run model providers, change Git state, or execute arbitrary code. A successful
preflight is **not** proof of a sandbox or an autonomous coding run.

## Windows PowerShell
From the Kevin checkout:

```powershell
Set-Location D:\projetos\kevin
powershell -NoProfile -File .\scripts\windows-preflight.ps1
```

Expected checks: Python, Git, Docker **daemon**, WSL distributions (informational),
OpenCode, optional AgentField Python package, Git checkout and Kevin origin.
A missing AgentField package is reported but is not automatically installed.
Review failures before proceeding. The script exits 1 if a required check fails.

## Security boundary for the next phase
The existing `local-tool` backend supports only a restricted `Write` operation;
it is **not** an autonomous coder or OS/container sandbox. Git worktrees provide
Git state isolation, not a process security boundary. A future end-to-end run
must execute against a disposable repository inside a verified container,
with network and host mounts explicitly constrained, no secrets, no provider
calls unless separately authorized, and no automatic GitHub push/merge.

## Acceptance for next PR
- Demonstrate Docker Engine and Linux container availability on Windows.
- Build a disposable fixture and run a deterministic tool operation inside the container.
- Verify host path isolation, timeout, output limits and failure behavior.
- Document the gap between deterministic tool execution and real model-driven coding.
- Keep all changes off `main` until CI and review pass.
