# Use a native stand-in for Cargo to check which side of -- receives the flag.
$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot 'test.ps1'
$dir = Join-Path ([IO.Path]::GetTempPath()) ('xcl-test-args-' + [guid]::NewGuid())
$null = New-Item -ItemType Directory -Path $dir
$cargo = Join-Path $dir 'cargo.cmd'
$tokens = Join-Path $dir 'args.txt'
$log = Join-Path $dir 'runner.log'
$oldPath = $env:PATH
Push-Location
try {
    @'
@echo off
if "%1"=="build" exit /b 0
if not "%1"=="test" exit /b 29
shift /1
:next
if "%~1"=="" goto done
>>"%~dp0args.txt" echo(%~1
shift /1
goto next
:done
>&2 echo SKIPPED fixture: synthetic reason
exit /b 101
'@ | Set-Content -LiteralPath $cargo -Encoding Ascii
    $env:PATH = $dir
    if ((Get-Command cargo).Path -ne $cargo) { throw 'Expected the native Cargo fixture' }
    & $runner --skip 'fixture with spaces' *> $log
    if ($LASTEXITCODE -ne 101) { throw "Lost Cargo test failure: $LASTEXITCODE" }

    $argsSeen = @([IO.File]::ReadAllLines($tokens))
    $separator = [array]::IndexOf($argsSeen, '--')
    $flag = [array]::IndexOf($argsSeen, '--no-fail-fast')
    if ($flag -lt 0 -or $flag -ge $separator -or $flag -ne [array]::LastIndexOf($argsSeen, '--no-fail-fast')) {
        throw "Expected --no-fail-fast once on the Cargo side: $argsSeen"
    }
    $testArgs = @($argsSeen | Select-Object -Skip ($separator + 1))
    if ($testArgs.Count -lt 2 -or $testArgs[-2] -ne '--skip' -or $testArgs[-1] -ne 'fixture with spaces') {
        throw "Unexpected test arguments: $testArgs"
    }
    if (!([IO.File]::ReadAllText($log)).Contains('GPU tests skipped on this adapter: 1 (synthetic reason)')) {
        throw 'Lost skip summary on a failing test run'
    }
    'test-no-fail-fast: ok'
} finally {
    Pop-Location
    $env:PATH = $oldPath
    foreach ($path in $tokens, $log, $cargo, $dir) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
    }
}
exit 0
