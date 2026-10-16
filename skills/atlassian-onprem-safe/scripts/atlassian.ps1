# Python 3.10+ must be installed and available as python or py.
$ErrorActionPreference = 'Stop'
$client = Join-Path $PSScriptRoot 'atlassian.py'
if (Get-Command python -ErrorAction SilentlyContinue) {
    & python $client @args
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 $client @args
} else {
    throw 'Python 3.10+ is required. Install Python, then run this command again.'
}
exit $LASTEXITCODE
