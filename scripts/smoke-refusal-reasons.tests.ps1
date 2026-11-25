# Exercise the smoke block using a synthetic log and the report's optional list of reasons.
$ErrorActionPreference = 'Stop'
$smoke = Join-Path $PSScriptRoot 'smoke.ps1'
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('xcl-smoke-reasons-' + [guid]::NewGuid())
$null = New-Item -ItemType Directory -Path $fixture
$xcl = Join-Path $fixture 'xcl.cmd'
$log = Join-Path $fixture 'xcl.log'
$report = Join-Path $fixture 'report.json'
$oldNetwork = $env:XCL_NETWORK
$oldSeconds = $env:XCL_RUN_SECONDS
$oldActivity = $env:XCL_ACTIVITY

function Get-CimInstance { [pscustomobject]@{Name = 'Fixture GPU'} }
function Assert-Reasons($expected) {
    $block = (& $smoke -Game $fixture -Xcl $xcl -Seconds 1) -split '\r?\n'
    if ($block -notcontains "refusal reasons (max 40): $expected") {
        throw "Expected $expected refusal reasons in the smoke block: $block"
    }
}
try {
    [IO.File]::WriteAllText($xcl, "@echo off`r`necho Log: %~dp0xcl.log`r`n")
    [IO.File]::WriteAllText($log, '(1 frames shown, 1 PresentX calls)')
    Assert-Reasons 'n/a'
    foreach ($json in '{', '{}', '{"d3d12":{}}', '{"d3d12":{"translation_errors":null}}') {
        [IO.File]::WriteAllText($report, $json)
        Assert-Reasons 'n/a'
    }
    foreach ($count in 0, 1, 2, 40) {
        $reasons = @(for ($i = 0; $i -lt $count; $i++) { "reason $i" })
        $json = @{d3d12 = @{adapter = 'Fixture GPU'; translation_errors = $reasons}} | ConvertTo-Json -Depth 4
        [IO.File]::WriteAllText($report, $json)
        Assert-Reasons $count
    }
    'smoke-refusal-reasons: 9 cases passed'
} finally {
    $env:XCL_NETWORK = $oldNetwork
    $env:XCL_RUN_SECONDS = $oldSeconds
    $env:XCL_ACTIVITY = $oldActivity
    foreach ($path in $xcl, $log, $report, $fixture) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
    }
}
