# A directory exists but cannot be started. Exercise restoration when Process.Start throws.
$ErrorActionPreference = 'Stop'
$smoke = Join-Path $PSScriptRoot 'smoke.ps1'
$original = $env:XCL_D3D12_DEBUG
$network, $seconds, $activity = $env:XCL_NETWORK, $env:XCL_RUN_SECONDS, $env:XCL_ACTIVITY
try {
    foreach ($initial in $null, 'previous') {
        $env:XCL_D3D12_DEBUG = $initial
        $failed = $false
        try { $null = & $smoke -Game fixture -Title fixture -Xcl $PSScriptRoot -DebugLayer }
        catch [System.Management.Automation.MethodInvocationException] {
            if ($_.Exception.InnerException -isnot [ComponentModel.Win32Exception]) { throw }
            $failed = $true
        }
        if (-not $failed) { throw 'Expected Process.Start to fail' }
        if ($env:XCL_D3D12_DEBUG -cne $initial) { throw 'Failed launch changed XCL_D3D12_DEBUG in the caller' }
    }
} finally {
    $env:XCL_D3D12_DEBUG = $original
    $env:XCL_NETWORK, $env:XCL_RUN_SECONDS, $env:XCL_ACTIVITY = $network, $seconds, $activity
}
