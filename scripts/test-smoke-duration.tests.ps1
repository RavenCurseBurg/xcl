# Run with powershell.exe or pwsh.exe. No title or executable is needed.
$ErrorActionPreference = 'Stop'
$smoke = Join-Path $PSScriptRoot 'smoke.ps1'
$missingExe = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString() + '.exe')

foreach ($duration in @(-121, -1, 2147364)) {
    try {
        & $smoke -Game 'unused' -Seconds $duration -Xcl $missingExe
    } catch {
        if ($_.FullyQualifiedErrorId -like 'ParameterArgumentValidationError,*') { continue }
        throw
    }
    throw "Expected parameter validation to reject -Seconds $duration."
}

foreach ($duration in @(0, 1, 2147363)) {
    try {
        & $smoke -Game 'unused' -Seconds $duration -Xcl $missingExe
    } catch {
        if ($_.Exception.Message.StartsWith("no $missingExe - build it first")) { continue }
        throw
    }
    throw "Expected -Seconds $duration to pass validation and reach the executable check."
}
