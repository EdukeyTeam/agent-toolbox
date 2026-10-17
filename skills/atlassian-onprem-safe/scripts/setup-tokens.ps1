$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'atlassian.ps1') setup
exit $LASTEXITCODE
