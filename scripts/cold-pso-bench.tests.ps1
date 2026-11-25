# Run with powershell.exe or pwsh.exe. Checks cold-pso-bench.ps1 against a fixture xcl.exe: the
# environment each run gets (driver blobs and implicit caches off, the thread count, its own
# times file, an exe name of its own that is removed afterwards), and the table it makes from
# XCL_PIPELINE_TIMES rows.
$ErrorActionPreference = 'Stop'
$bench = Join-Path $PSScriptRoot 'cold-pso-bench.ps1'
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('xcl-cold-pso-' + [guid]::NewGuid())
$null = New-Item -ItemType Directory -Path $fixture
$fixtureRoot = (Resolve-Path -LiteralPath $fixture).ProviderPath
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
if (-not $fixtureRoot.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) { throw "fixture outside temporary directory: $fixtureRoot" }
$savedAppData = $env:LOCALAPPDATA
$savedTimes = $env:XCL_PIPELINE_TIMES
$savedCacheOff = $env:XCL_PIPELINE_CACHE_OFF
try {
    # The fixture must never clear the user's driver cache or append to a real timing file.
    $env:LOCALAPPDATA = Join-Path $fixture 'local-appdata'
    $cache = Join-Path $env:LOCALAPPDATA 'NVIDIA\DXCache'
    $null = New-Item -ItemType Directory -Path $cache
    $sentinel = Join-Path $cache 'sentinel'
    [IO.File]::WriteAllText($sentinel, 'temporary fixture cache')
    Remove-Item Env:XCL_PIPELINE_TIMES, Env:XCL_PIPELINE_CACHE_OFF -ErrorAction SilentlyContinue
    $xcl = Join-Path $fixture 'xcl.cmd'
    # A pipelines run (XCL_PIPELINE_TIMES set) writes four builds and the environment it saw.
    [IO.File]::WriteAllText($xcl, (@(
        '@echo off'
        'if not defined XCL_PIPELINE_TIMES exit /b 0'
        '>> "%XCL_PIPELINE_TIMES%" echo 0000000000000001,1000,made,1.0,100.0'
        '>> "%XCL_PIPELINE_TIMES%" echo 0000000000000002,100000,made,0.5,300.0'
        '>> "%XCL_PIPELINE_TIMES%" echo 0000000000000003,2000000,made,0.0,5000.0'
        '>> "%XCL_PIPELINE_TIMES%" echo 0000000000000004,500,refused,0.0,1.0'
        '>> "%~dp0env-%XCL_PIPELINE_THREADS%.txt" echo %~n0 %XCL_PSO_DISK_CACHE% %XCL_PIPELINE_CACHE_OFF% %*'
        'exit /b 0'
    ) -join "`r`n") + "`r`n")
    $out = Join-Path $fixture 'out'
    $table = (& $bench -Shaders 'D:\pack' -Threads 4, 8 -Limit 10 -Xcl $xcl -Out $out) -join "`n"

    $names = @()
    foreach ($n in 4, 8) {
        $seen = (Get-Content (Join-Path $fixture "env-$n.txt") -Raw).Trim()
        if ($seen -notmatch "^xcl-cold-$n-[0-9a-f]{8} 0 1 shaders D:\\pack --precompile --only cs --limit 10 --pipelines$") { throw "threads ${n}: exe name, environment or arguments wrong: $seen" }
        $names += ($seen -split ' ')[0]
        # made: 0.1 + 0.3 + 5.0 s; p50 of three is the second, p95 and max the third
        if ($table -notmatch "\| $n \| [\d.]+ \| [\d.]+ \| \d+ \| 3 \| 1 \| 5\.4 \| 0\.3 \| 5 \| 5 \|") { throw "threads ${n}: summary row wrong:`n$table" }
        foreach ($row in @("\| $n \| < 64 KiB \| 1 \| 0\.1 \|", "\| $n \| 64-256 KiB \| 1 \| 0\.3 \|", "\| $n \| 1-4 MiB \| 1 \| 5 \|")) {
            if ($table -notmatch $row) { throw "threads ${n}: bucket row missing ($row):`n$table" }
        }
    }
    if (-not (Test-Path (Join-Path $out 'summary.csv'))) { throw 'no summary.csv' }
    # a new exe name for each run (the AMD driver's cache key), none left behind
    if ($names[0] -eq $names[1]) { throw "two runs used one exe name: $($names[0])" }
    $left = @(Get-ChildItem $fixture -Filter 'xcl-cold-*')
    if ($left.Count) { throw "exe copies left: $($left.Name -join ', ')" }

    # from cmd or bash (`-File`) "3,5" arrives as one string: two runs, not one of 35 threads
    $shell = (Get-Process -Id $PID).Path
    $null = & $shell -NoProfile -ExecutionPolicy Bypass -File $bench -Shaders 'D:\pack' -Threads '3,5' -Xcl $xcl -Out (Join-Path $fixture 'out3')
    if ($LASTEXITCODE) { throw "-File -Threads 3,5 failed ($LASTEXITCODE)" }
    if (-not ((Test-Path (Join-Path $fixture 'env-3.txt')) -and (Test-Path (Join-Path $fixture 'env-5.txt')))) { throw '-File -Threads 3,5 did not run 3 and 5 threads' }
    if (Test-Path (Join-Path $fixture 'env-35.txt')) { throw '-File -Threads 3,5 ran 35 threads' }
    $refused = $false
    try { & $bench -Shaders 'D:\pack' -Threads '4,x' -Xcl $xcl -Out (Join-Path $fixture 'out4') *> $null } catch { $refused = $_.Exception.Message -match "-Threads: 'x'" }
    if (-not $refused) { throw '-Threads 4,x was not refused' }

    # -ClearNvCache replaces the implicit-cache switch
    $cachePath = (Resolve-Path -LiteralPath $cache).ProviderPath
    if (-not $cachePath.StartsWith($fixtureRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "cache outside fixture: $cachePath" }
    & $bench -Shaders 'D:\pack' -Threads 6 -Xcl $xcl -Out (Join-Path $fixture 'out2') -ClearNvCache *> $null
    $seen = (Get-Content (Join-Path $fixture 'env-6.txt') -Raw).Trim()
    if ($seen -notmatch '^xcl-cold-6-[0-9a-f]{8} 0 +shaders D:\\pack --precompile --only cs --pipelines$') { throw "-ClearNvCache: caches switch still set: $seen" }
    if (Test-Path -LiteralPath $sentinel) { throw '-ClearNvCache: temporary cache was not cleared' }

    # An exit-zero process may still leave missing or corrupt timings. Keep every case's
    # result so a baseline run reports the whole matrix, not only its first failure.
    $source = Join-Path $fixture 'fixture-times.csv'
    [IO.File]::WriteAllText($xcl, (@(
        '@echo off'
        'if not defined XCL_PIPELINE_TIMES exit /b 0'
        'if exist "%~dp0fixture-times.csv" type "%~dp0fixture-times.csv" >> "%XCL_PIPELINE_TIMES%"'
        'exit /b 0'
    ) -join "`r`n") + "`r`n")
    $good = '0000000000000001,1,made,0,0'
    $cases = @(
        @{ Name = 'missing'; Data = $null; Error = 'is missing' }
        @{ Name = 'empty'; Data = ''; Error = 'has no measurement rows' }
        @{ Name = 'blank-only'; Data = "  `r`n`t`r`n"; Error = 'has no measurement rows' }
    )
    $badRows = @(
        @{ Name = 'truncated'; Row = '0000000000000001,1,made,0' }
        @{ Name = 'extra-field'; Row = '0000000000000001,1,made,0,0,extra' }
        @{ Name = 'hash-short'; Row = '1,1,made,0,0' }
        @{ Name = 'hash-long'; Row = '00000000000000001,1,made,0,0' }
        @{ Name = 'hash-nonhex'; Row = '000000000000000g,1,made,0,0' }
        @{ Name = 'unknown-outcome'; Row = '0000000000000001,1,unknown,0,0' }
    )
    foreach ($value in @('', 'bogus', '1.5', '1e3', '9223372036854775808', '0', '-1')) {
        $badRows += @{ Name = "bytes-$value"; Row = "0000000000000001,$value,made,0,0" }
    }
    foreach ($field in @('wait', 'driver')) {
        foreach ($value in @('', 'bogus', '-0.5', 'NaN', 'Infinity', '-Infinity', '1e309')) {
            $row = if ($field -eq 'wait') { "0000000000000001,1,made,$value,0" } else { "0000000000000001,1,made,0,$value" }
            $badRows += @{ Name = "$field-$value"; Row = $row }
        }
    }
    foreach ($bad in $badRows) {
        $cases += @{ Name = $bad.Name; Data = "$good`r`n`r`n$($bad.Row)`r`n"; Line = 3 }
    }
    foreach ($outcome in @('made', 'refused', 'reused')) {
        $cases += @{ Name = "valid-$outcome-zero"; Data = "0000000000000001,1,$outcome,0,0`r`n"; Counts = @([int]($outcome -eq 'made'), [int]($outcome -eq 'refused'), [int]($outcome -eq 'reused')) }
    }
    $cases += @{ Name = 'valid-blank-lines'; Data = "`r`n$good`r`n `r`n0000000000000002,2,refused,0,0`r`n0000000000000003,3,reused,0,0`r`n"; Counts = @(1, 1, 1) }
    $cases += @{ Name = 'valid-negative-zero'; Data = "0000000000000001,1,made,-0.0,-0.0`r`n"; Counts = @(1, 0, 0) }
    $cases += @{ Name = 'valid-[literal]-path'; Data = "$good`r`n"; Counts = @(1, 0, 0) }
    # XCL appends: reusing an output directory must remove its previous timings first.
    $cases += @{ Name = 'valid-literal-path-rerun'; OutName = 'valid-[literal]-path'; Data = "$good`r`n"; Counts = @(1, 0, 0) }
    $cases += @{ Name = 'invalid-after-valid'; OutName = 'valid-[literal]-path'; Data = "bad row`r`n"; Line = 1 }
    $failures = New-Object 'System.Collections.Generic.List[string]'
    $passed = 0
    foreach ($case in $cases) {
        if ($null -eq $case.Data) { Remove-Item -LiteralPath $source -ErrorAction SilentlyContinue }
        else { [IO.File]::WriteAllText($source, $case.Data) }
        $outName = if ($case.ContainsKey('OutName')) { $case.OutName } else { $case.Name }
        $caseOut = Join-Path $fixture ('case-' + $outName)
        $summary = Join-Path $caseOut 'summary.csv'
        $timing = Join-Path $caseOut 'times-1.csv'
        $errorText = $null
        try { & $bench -Shaders 'D:\pack' -Threads 1 -Xcl $xcl -Out $caseOut *> $null }
        catch { $errorText = $_.Exception.Message }
        $problems = New-Object 'System.Collections.Generic.List[string]'
        if ($case.ContainsKey('Counts')) {
            if ($errorText) { $problems.Add("unexpected error: $errorText") }
            elseif (-not (Test-Path -LiteralPath $summary)) { $problems.Add('no summary.csv') }
            else {
                $rows = @(Import-Csv -LiteralPath $summary)
                if ($rows.Count -ne 1) { $problems.Add("expected one summary row, got $($rows.Count)") }
                else {
                    $counts = @([int]$rows[0].made, [int]$rows[0].refused, [int]$rows[0].reused) -join ','
                    if ($counts -ne ($case.Counts -join ',')) { $problems.Add("wrong outcome counts: $counts") }
                    foreach ($metric in @('driver_s', 'p50_s', 'p95_s', 'max_s')) {
                        if ([double]$rows[0].$metric -ne 0) { $problems.Add("$metric should be zero") }
                    }
                }
            }
        } else {
            if (-not $errorText) { $problems.Add('invalid timing file accepted') }
            else {
                $prefix = [regex]::Escape("timing file '$timing'")
                $expected = if ($case.ContainsKey('Line')) { "^${prefix}, line $($case.Line): .+" } else { "^$prefix $($case.Error)$" }
                if ($errorText -notmatch $expected) { $problems.Add("wrong diagnostic: $errorText") }
            }
            if (Test-Path -LiteralPath $summary) { $problems.Add('published summary.csv for invalid timings') }
        }
        $copies = @(Get-ChildItem -LiteralPath $fixture -Filter 'xcl-cold-*')
        if ($copies.Count) { $problems.Add("exe copies left: $($copies.Name -join ', ')") }
        if ($problems.Count) {
            $failure = "$($case.Name): $($problems -join '; ')"
            $failures.Add($failure)
            Write-Host "FAIL $failure"
        } else { $passed++; Write-Host "PASS $($case.Name)" }
    }
    Write-Host "timing validation: $passed passed, $($failures.Count) failed, $($cases.Count) cases"
    if ($failures.Count) { throw "$($failures.Count) timing validation cases failed" }
    'cold-pso-bench.ps1: ok'
} finally {
    $env:LOCALAPPDATA = $savedAppData
    $env:XCL_PIPELINE_TIMES = $savedTimes
    $env:XCL_PIPELINE_CACHE_OFF = $savedCacheOff
    $cleanup = (Resolve-Path -LiteralPath $fixture).ProviderPath
    if ($cleanup -ne $fixtureRoot -or -not $cleanup.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) { throw "cleanup outside fixture: $cleanup" }
    Remove-Item -LiteralPath $cleanup -Recurse -Force -ErrorAction SilentlyContinue
}
