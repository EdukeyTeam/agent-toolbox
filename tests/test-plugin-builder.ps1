[CmdletBinding()]
param(
    [string]$BuilderPath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts/build-claude-plugin.ps1')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$fixtureRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('plugin-builder-test-' + [Guid]::NewGuid().ToString('N'))
$pwsh = (Get-Process -Id $PID).Path

function New-Fixture {
    param([string]$Name, [switch]$ValidSkill)
    $root = Join-Path $fixtureRoot $Name
    $null = New-Item -ItemType Directory -Path (Join-Path $root 'scripts'), (Join-Path $root '.claude-plugin') -Force
    Copy-Item -LiteralPath $BuilderPath -Destination (Join-Path $root 'scripts/build-claude-plugin.ps1')
    @{ name = 'agent-toolbox'; version = '0.0.0'; description = 'Synthetic test plugin' } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root '.claude-plugin/plugin.json') -Encoding utf8
    if ($ValidSkill) {
        $skill = Join-Path $root 'skills/known-skill'
        $null = New-Item -ItemType Directory -Path (Join-Path $skill 'references') -Force
        "---`nname: known-skill`ndescription: Valid synthetic skill.`n---`n# Fixture" |
            Set-Content -LiteralPath (Join-Path $skill 'SKILL.md') -Encoding utf8
        '# Valid reference' | Set-Content -LiteralPath (Join-Path $skill 'references/guide.md') -Encoding utf8
    }
    return $root
}

function Invoke-Fixture {
    param([string]$Root)
    $PSNativeCommandUseErrorActionPreference = $false
    $output = & $pwsh -NoProfile -File (Join-Path $Root 'scripts/build-claude-plugin.ps1') `
        -OutputDirectory (Join-Path $Root 'out') -SkipClaudeValidation 2>&1 | Out-String
    return @{ ExitCode = $LASTEXITCODE; Output = $output }
}

try {
    $valid = New-Fixture -Name 'valid' -ValidSkill
    $result = Invoke-Fixture -Root $valid
    if ($result.ExitCode -ne 0) { throw "Valid plugin failed: $($result.Output)" }
    $zips = @(Get-ChildItem -LiteralPath (Join-Path $valid 'out') -Filter '*.zip')
    if ($zips.Count -ne 1) { throw 'Valid plugin did not create exactly one ZIP.' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($zips[0].FullName)
    try {
        $entries = @($archive.Entries | ForEach-Object { $_.FullName })
        foreach ($entry in @('agent-toolbox/skills/known-skill/SKILL.md', 'agent-toolbox/skills/known-skill/references/guide.md')) {
            if ($entries -notcontains $entry) { throw "Valid plugin omitted $entry" }
        }
    }
    finally { $archive.Dispose() }
    Write-Output 'PASS: valid skill and reference are packaged.'

    foreach ($withValid in @($true, $false)) {
        $root = New-Fixture -Name "missing-skill-$withValid" -ValidSkill:$withValid
        $references = Join-Path $root 'skills/new-skill/references'
        $null = New-Item -ItemType Directory -Path $references -Force
        '# Missing entrypoint' | Set-Content -LiteralPath (Join-Path $references 'guide.md') -Encoding utf8
        $result = Invoke-Fixture -Root $root
        if ($result.ExitCode -eq 0) { throw 'Builder accepted a reference-only skill directory without SKILL.md.' }
        if ($result.Output -notmatch 'has no SKILL\.md') { throw "Failure did not explain the missing entrypoint: $($result.Output)" }
        if (@(Get-ChildItem -LiteralPath (Join-Path $root 'out') -Filter '*.zip').Count -ne 0) {
            throw 'Invalid skill left a publishable ZIP.'
        }
        Write-Output "PASS: missing SKILL.md rejected with existing valid skill=$withValid; no ZIP created."
    }
}
finally {
    $tempPrefix = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if (-not [System.IO.Path]::GetFullPath($fixtureRoot).StartsWith($tempPrefix, [StringComparison]::Ordinal)) {
        throw 'Refusing to clean a test fixture outside the temporary directory.'
    }
    if (Test-Path -LiteralPath $fixtureRoot) { Remove-Item -LiteralPath $fixtureRoot -Recurse -Force }
}
