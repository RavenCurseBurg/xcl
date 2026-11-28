# Run with powershell.exe or pwsh.exe. `test.ps1 -Brief` against a fake Cargo: the console keeps the
# failures, the skip summary and the summed counts; the log keeps every line.
$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot 'test.ps1'
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('xcl-test-brief-' + [guid]::NewGuid())
$null = New-Item -ItemType Directory -Path $fixture
$cargo = Join-Path $fixture 'cargo.cmd'
$console = Join-Path $fixture 'console.txt'
$full = Join-Path $fixture 'full.txt'
$oldPath = $env:PATH
$oldLog = $env:XCL_TEST_LOG
$oldBenchFailure = $env:XCL_TEST_BENCH_FAIL
Push-Location
try {
    $env:PATH = $fixture
    $env:XCL_TEST_LOG = $full
    $env:XCL_TEST_BENCH_FAIL = '0'
    [IO.File]::WriteAllText($full, 'previous test run')
    # A broken runner may leave the log open. Let the child close its handles before reading it.
    & (Get-Process -Id $PID).Path -NoProfile -NonInteractive -Command {
        param($runnerPath)
        $ProgressPreference = 'SilentlyContinue'
        try { & $runnerPath -Brief *> $null }
        catch [System.Management.Automation.CommandNotFoundException] { exit 0 }
        exit 1
    } -Args $runner
    if ($LASTEXITCODE -ne 0) { throw 'Expected the runner to report missing Cargo.' }
    if ([IO.File]::ReadAllText($full) -cne 'previous test run') { throw 'Missing Cargo changed the previous log.' }

    @'
@echo off
if "%1"=="build" (
    >&2 echo    Compiling xcl v0.1.0
    exit /b 0
)
if "%1"=="bench" goto bench
if "%1"=="test" (
    echo running 3 tests
    echo test area::passes_one ... ok
    echo test area::passes_two ... ok
    echo test area::breaks ... FAILED
    echo.
    echo failures:
    echo.
    echo ---- area::breaks stdout ----
    echo thread 'area::breaks' panicked at src/area.rs:7:5: synthetic panic
    echo.
    echo test result: FAILED. 2 passed; 1 failed; 4 ignored; 0 measured; 0 filtered out; finished in 0.01s
    echo running 1 test
    echo test gpu::wave ... ok
    >&2 echo SKIPPED gpu::wave: synthetic reason
    echo test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s
    exit /b 101
)
exit /b 127

:bench
echo benchmark smoke %~2 %~3 %~4 %~5 %~6 %~7
if "%XCL_TEST_BENCH_FAIL%"=="1" goto bench_fail
exit /b 0

:bench_fail
>&2 echo error: synthetic benchmark failure
exit /b 43
'@ | Set-Content -LiteralPath $cargo -Encoding Ascii
    if ((Get-Command cargo).Path -ne $cargo) { throw 'The native Cargo fixture was not selected.' }

    & $runner -Brief *> $console
    if ($LASTEXITCODE -ne 101) { throw "Runner exited $LASTEXITCODE, expected Cargo's 101." }
    # a redirected Windows PowerShell 5.1 host wraps long lines: compare without the line breaks
    $shown = (Get-Content -LiteralPath $console -Raw) -replace "`r?`n", ''
    $logged = Get-Content -LiteralPath $full -Raw
    if ($logged.Contains('previous test run')) { throw 'The new run kept output from the previous run.' }
    foreach ($want in "synthetic panic", "GPU tests skipped on this adapter: 1 (synthetic reason)",
        "tests: 3 passed, 1 failed, 4 ignored (2 test binaries); exit 101; full output: $full") {
        if (!$shown.Contains($want)) { throw "Console lacks: $want" }
    }
    if ($shown.Contains('passes_one ... ok') -or $shown.Contains('Compiling') -or $shown.Contains('benchmark smoke')) {
        throw 'Brief console shows passing tests or stage progress.'
    }
    foreach ($want in 'Compiling xcl', 'benchmark smoke -p xcl --bench * -- --test', 'test area::passes_one ... ok', 'synthetic panic', 'test gpu::wave ... ok') {
        if (!$logged.Contains($want)) { throw "Log lacks: $want" }
    }

    $env:XCL_TEST_BENCH_FAIL = '1'
    & $runner -Brief *> $console
    if ($LASTEXITCODE -ne 43) { throw "Failed benchmark returned $LASTEXITCODE, expected 43." }
    $shown = (Get-Content -LiteralPath $console -Raw) -replace "\r?\n", ''
    $logged = [IO.File]::ReadAllText($full)
    if (!$shown.Contains('error: synthetic benchmark failure') -or !$shown.Contains('bench failed')) {
        throw 'Brief console is missing the benchmark failure.'
    }
    if (!$logged.Contains('error: synthetic benchmark failure') -or $logged.Contains('running 3 tests')) {
        throw 'Expected a complete benchmark error log and no subsequent tests.'
    }
} finally {
    Pop-Location
    $env:PATH = $oldPath
    $env:XCL_TEST_LOG = $oldLog
    $env:XCL_TEST_BENCH_FAIL = $oldBenchFailure
    foreach ($path in $cargo, $console, $full, $fixture) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
    }
}
