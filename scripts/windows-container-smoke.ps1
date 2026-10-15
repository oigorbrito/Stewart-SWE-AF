#requires -Version 5.1
<#
.SYNOPSIS
Run a deterministic Kevin smoke test inside a disposable Linux container.
No model calls, Git writes, host workspace mounts, or container network.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$Image = 'python:3.12-alpine'
$Name = 'kevin-smoke-' + [guid]::NewGuid().ToString('N').Substring(0, 12)
$Payload = @'
import pathlib
import tempfile

with tempfile.TemporaryDirectory(prefix="kevin-") as directory:
    root = pathlib.Path(directory).resolve()
    target = root / "result.txt"
    target.write_text("Kevin isolated smoke OK\n", encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "Kevin isolated smoke OK\n"
    assert target.resolve().is_relative_to(root)
    print("PASS: deterministic write/read within disposable container workspace")
    print("PASS: container network disabled and host directory not mounted (Docker flags)")
'@
try {
    & docker info --format '{{.ServerVersion}}' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Engine unavailable; start Docker Desktop first.' }
    # Pull is explicit and happens before --network none, because the daemon
    # may need network access to fetch an image not present locally.
    & docker image inspect $Image *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Output "Image missing; pulling $Image (network used only for image download)."
        & docker pull $Image
        if ($LASTEXITCODE -ne 0) { throw 'Docker image pull failed.' }
    }
    $Payload | & docker run --rm --name $Name --network none --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 128m --cpus 1 --tmpfs /tmp:rw,noexec,nosuid,size=16m --workdir /tmp --user 65534:65534 -i $Image python -
    if ($LASTEXITCODE -ne 0) { throw 'Container smoke failed.' }
    Write-Output 'PASS: Kevin container smoke complete. No host directories mounted.'
} finally {
    # Best-effort cleanup on interruption; the container also uses --rm.
    & docker rm -f $Name 2>$null | Out-Null
}
