# Run under Windows PowerShell or pwsh. No profiler is installed or started.
$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot 'flamegraph.ps1'
$root = Join-Path ([IO.Path]::GetTempPath()) ('xcl-flamegraph-' + [guid]::NewGuid())
$null = [IO.Directory]::CreateDirectory($root)
$output = Join-Path $root 'result.svg'
$marker = Join-Path $root 'invoked.txt'
$oldPath = $env:PATH
$cwd = (Get-Location).Path

function Assert-Rejected($bench, $reason) {
    $failure = $null
    try { & $runner -Bench $bench -Output $output } catch { $failure = $_ }
    if (-not $failure -or $failure.Exception.Message -notmatch $reason) {
        throw "Expected '$reason' for '$bench', got '$failure'."
    }
    if ((Test-Path -LiteralPath $marker) -or (Test-Path -LiteralPath $output)) {
        throw 'Preflight started a command or created an output file.'
    }
    if ((Get-Location).Path -ne $cwd) { throw 'Preflight changed the caller directory.' }
}

try {
    $env:PATH = $root
    $stub = "@echo off`r`n>>`"%~dp0invoked.txt`" echo invoked`r`nexit /b 91`r`n"
    [IO.File]::WriteAllText((Join-Path $root 'cargo.cmd'), $stub)
    Assert-Rejected 'not-a-benchmark' 'not-a-benchmark'
    Assert-Rejected 'core' 'cargo-flamegraph is not installed'
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        [IO.File]::WriteAllText((Join-Path $root 'cargo-flamegraph.cmd'), $stub)
        Assert-Rejected 'runtime' 'requires an elevated PowerShell'
        Write-Output 'PASS: non-elevated profiler check'
    }
    Write-Output 'PASS: invalid benchmark and missing profiler'
} finally {
    $env:PATH = $oldPath
    foreach ($name in 'cargo.cmd', 'cargo-flamegraph.cmd', 'invoked.txt', 'result.svg') {
        $file = Join-Path $root $name
        if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file }
    }
    [IO.Directory]::Delete($root)
}
