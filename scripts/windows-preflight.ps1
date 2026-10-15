#requires -Version 5.1
<#
.SYNOPSIS
Read-only Windows preflight for Kevin local development.
.DESCRIPTION
Checks CLI presence, Docker daemon, WSL distributions, repository identity,
AgentField package and OpenCode. Does not install, start, or mutate anything.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Continue'
$failed = $false
function Report([string]$Name, [bool]$Ok, [string]$Detail, [bool]$Required = $true) {
    $state = if ($Ok) { 'PASS' } elseif ($Required) { 'BLOCKED' } else { 'INFO' }
    Write-Output ("[{0}] {1}: {2}" -f $state, $Name, $Detail)
    if (-not $Ok -and $Required) { $script:failed = $true }
}
function Probe([string]$Name, [string[]]$Arguments) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) { return @{ Ok = $false; Text = 'command not found' } }
    try {
        $output = & $Name @Arguments 2>&1 | Out-String
        $ok = ($LASTEXITCODE -eq 0)
        return @{ Ok = $ok; Text = ($output.Trim() -replace '[\r\n]+', ' | ') }
    } catch {
        return @{ Ok = $false; Text = $_.Exception.Message }
    }
}
$python = Probe 'python' @('--version')
Report 'Python' $python.Ok $python.Text
$git = Probe 'git' @('--version')
Report 'Git' $git.Ok $git.Text
$docker = Probe 'docker' @('info','--format','{{.ServerVersion}}')
Report 'Docker Engine' $docker.Ok $docker.Text
$wsl = Probe 'wsl' @('--list','--verbose')
Report 'WSL distributions' $wsl.Ok $wsl.Text $false
$opencode = Probe 'opencode' @('--version')
Report 'OpenCode' $opencode.Ok $opencode.Text
$agentfield = Probe 'python' @('-m','pip','show','agentfield')
Report 'AgentField Python package' $agentfield.Ok $(if ($agentfield.Ok) { 'installed' } else { 'not installed in selected Python environment' }) $false
$root = Probe 'git' @('rev-parse','--show-toplevel')
Report 'Git checkout' $root.Ok $root.Text
if ($root.Ok) {
    $remote = Probe 'git' @('remote','get-url','origin')
    $expected = $remote.Ok -and ($remote.Text -match '(?i)(github\.com[:/])oigorbrito/kevin(\.git)?$')
    Report 'Kevin origin' $expected $(if ($remote.Ok) { $remote.Text } else { 'origin missing' })
    $status = Probe 'git' @('status','--porcelain')
    Report 'Local changes preserved' $status.Ok $(if ($status.Ok) { 'status inspected; no files modified' } else { $status.Text })
}
Write-Output 'Preflight is read-only. No isolated execution or model invocation has been performed.'
if ($failed) { exit 1 }
exit 0
