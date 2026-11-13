# Python 3.10+ must be installed and available as python or py.
$ErrorActionPreference = 'Stop'
$client = Join-Path $PSScriptRoot 'atlassian.py'
# Multiple PATH entries (for example a WindowsApps alias) must not become one filename.
$python = Get-Command python -CommandType Application -TotalCount 1 -ErrorAction SilentlyContinue
$pythonArgs = @($client) + @($args)
if (-not $python) {
    $python = Get-Command py -CommandType Application -TotalCount 1 -ErrorAction SilentlyContinue
    $pythonArgs = @('-3') + $pythonArgs
}
if (-not $python) {
    throw 'Python 3.10+ is required. Install Python, then run this command again.'
}

if ($env:OS -eq 'Windows_NT') {
    # Avoid Windows PowerShell 5.1 native marshalling, which strips embedded JQL/CQL quotes.
    # Quote each argument for the Windows CRT: double backslashes before quotes and at the end.
    $quoted = foreach ($value in $pythonArgs) {
        '"' + [regex]::Replace([regex]::Replace($value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
    }
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $python.Source
    $start.Arguments = $quoted -join ' '
    $start.UseShellExecute = $false
    $process = [System.Diagnostics.Process]::Start($start)
    $process.WaitForExit()
    $exitCode = $process.ExitCode
    $process.Dispose()
    exit $exitCode
} else {
    & $python.Source @pythonArgs
    exit $LASTEXITCODE
}
