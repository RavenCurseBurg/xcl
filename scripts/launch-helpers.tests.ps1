# Check the exit codes observed by callers of both helpers. No game files are used.
$ErrorActionPreference = 'Stop'
$tempRoot = (Resolve-Path -LiteralPath ([IO.Path]::GetTempPath())).Path.TrimEnd('\')
$root = Join-Path $tempRoot ('xcl-helper-exit-' + [guid]::NewGuid())
$shell = (Get-Process -Id $PID).Path
$originalPath = $env:PATH
try {
    $scripts = [IO.Directory]::CreateDirectory((Join-Path $root 'scripts')).FullName
    $release = [IO.Directory]::CreateDirectory((Join-Path $root 'target\release')).FullName
    $exe = Join-Path $release 'xcl.exe'
    $source = Join-Path $root 'fixture.cs'
    [IO.File]::WriteAllText($source, 'class Fixture { static int Main() { return 23; } }')
    $compiler = Join-Path $env:SystemRoot 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    & $compiler /nologo /target:exe "/out:$exe" $source
    if ($LASTEXITCODE -ne 0) { throw 'Could not build the native fixture' }

    foreach ($name in 'run-game.ps1', 'precompile-shaders.ps1') {
        $script = Join-Path $scripts $name
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $script
        & $shell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $script -Game fixture | Out-Null
        if ($LASTEXITCODE -ne 23) { throw "$name returned $LASTEXITCODE for a child that exited 23" }
    }

    [IO.File]::Delete($exe)
    [IO.File]::WriteAllText((Join-Path $root 'cargo.cmd'), "@exit /b 17`r`n")
    $env:PATH = $root
    & $shell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $scripts 'run-game.ps1') -Game fixture | Out-Null
    if ($LASTEXITCODE -ne 17) { throw "run-game.ps1 returned $LASTEXITCODE for a build that exited 17" }
    'launch helpers: 3 passed'
} finally {
    $env:PATH = $originalPath
    if (Test-Path -LiteralPath $root) {
        $resolved = (Resolve-Path -LiteralPath $root).Path
        if ([IO.Path]::GetDirectoryName($resolved) -ne $tempRoot) { throw 'Unexpected fixture path' }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
