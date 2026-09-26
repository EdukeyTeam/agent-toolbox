[CmdletBinding()]
param(
    [string]$OutputDirectory,
    [switch]$AllowDirtySource,
    [switch]$KeepStaging,
    [switch]$SkipClaudeValidation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-HexDigest {
    param([Parameter(Mandatory)][string]$Text)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        return (($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') }) -join '')
    }
    finally { $sha.Dispose() }
}

function Test-ProtectedPackagePath {
    param([Parameter(Mandatory)][string]$RelativePath)
    $leaf = Split-Path -Leaf $RelativePath
    if ((($leaf -like '*.env') -or ($leaf -like '*.env.*')) -and ($leaf -notlike '*.env.example')) {
        return $true
    }
    return (
        ($leaf -like '*.token') -or ($leaf -like '*.tokens') -or
        ($leaf -like 'cf-tokens*') -or ($leaf -like '*-secrets.json') -or
        ($leaf -like '*-credentials.json') -or ($leaf -eq 'gsc-client_secrets.json') -or
        ($leaf -like 'service_account*.json')
    )
}

function Get-PackagedSourceFiles {
    param([Parameter(Mandatory)][string]$SourceDirectory)
    $excludedDirectories = @('.git', 'node_modules', '.venv', 'venv', '__pycache__')
    $trimChars = @([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    $prefix = $SourceDirectory.TrimEnd($trimChars) + [System.IO.Path]::DirectorySeparatorChar
    foreach ($file in (Get-ChildItem -LiteralPath $SourceDirectory -Recurse -File -Force)) {
        $relativePath = $file.FullName.Substring($prefix.Length)
        $segments = $relativePath -split '[\\/]'
        if (@($segments | Where-Object { $excludedDirectories -contains $_ }).Count -gt 0) { continue }
        if ($file.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            throw "Refusing to package a linked file: $relativePath"
        }
        if (Test-ProtectedPackagePath -RelativePath $relativePath) {
            throw "Refusing to package protected-looking file: $relativePath"
        }
        [pscustomobject]@{ File = $file; RelativePath = $relativePath }
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$PluginName = 'agent-toolbox'
$SkillsRoot = Join-Path $repoRoot 'skills'
$manifestTemplatePath = Join-Path $repoRoot '.claude-plugin/plugin.json'
if (-not (Test-Path -LiteralPath $manifestTemplatePath -PathType Leaf)) {
    throw "Missing Claude plugin manifest: $manifestTemplatePath"
}

$SkillsRoot = (Resolve-Path -LiteralPath $SkillsRoot).Path
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path ([Environment]::GetFolderPath('UserProfile')) 'Downloads/Claude Plugins'
}
$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path

$skillNames = @(
    Get-ChildItem -LiteralPath $SkillsRoot -Directory |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'SKILL.md') -PathType Leaf } |
        ForEach-Object { $_.Name } | Sort-Object
)
if ($skillNames.Count -eq 0) { throw "Plugin '$PluginName' has no skills under skills/." }

$sourceCommit = 'installed-skills'
$gitMarker = Join-Path $repoRoot '.git'
if (Test-Path -LiteralPath $gitMarker) {
    $sourceCommit = (& git -C $repoRoot rev-parse HEAD 2>$null).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($sourceCommit)) {
        throw "Could not read the Git commit for source root: $SkillsRoot"
    }
    $dirty = @(& git -C $repoRoot status --porcelain --untracked-files=all)
    if ($LASTEXITCODE -ne 0) { throw "Could not check the Git working tree: $SkillsRoot" }
    if ($dirty.Count -gt 0 -and -not $AllowDirtySource) {
        throw 'The source checkout is dirty. Commit/review the source first, or pass -AllowDirtySource only for a development build.'
    }
    if ($dirty.Count -gt 0) { $sourceCommit = "$sourceCommit-dirty" }
}

$builtAt = [DateTime]::UtcNow
$versionPatch = [int]$builtAt.ToString('ddHHmmss')
$version = '{0}.{1}.{2}' -f $builtAt.Year, $builtAt.Month, $versionPatch
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("claude-plugin-{0}-{1}" -f $PluginName, [Guid]::NewGuid().ToString('N'))
$pluginRoot = Join-Path $tempRoot $PluginName
$pluginSkillsRoot = Join-Path $pluginRoot 'skills'
$hashRecords = [System.Collections.Generic.List[string]]::new()
$validatedWithClaude = $false

try {
    $null = New-Item -ItemType Directory -Path $pluginSkillsRoot -Force
    $null = New-Item -ItemType Directory -Path (Join-Path $pluginRoot '.claude-plugin') -Force
    foreach ($skillName in $skillNames) {
        if ($skillName -notmatch '^[a-z0-9-]+$') { throw "Invalid skill name '$skillName'." }
        $sourceSkill = Join-Path $SkillsRoot $skillName
        if (-not (Test-Path -LiteralPath (Join-Path $sourceSkill 'SKILL.md') -PathType Leaf)) {
            throw "Skill '$skillName' has no SKILL.md under skills/."
        }

        $destinationSkill = Join-Path $pluginSkillsRoot $skillName
        foreach ($sourceFile in (Get-PackagedSourceFiles -SourceDirectory $sourceSkill)) {
            $destinationFile = Join-Path $destinationSkill $sourceFile.RelativePath
            $null = New-Item -ItemType Directory -Path (Split-Path -Parent $destinationFile) -Force
            Copy-Item -LiteralPath $sourceFile.File.FullName -Destination $destinationFile
            $fileHash = (Get-FileHash -LiteralPath $sourceFile.File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            $portablePath = $sourceFile.RelativePath -replace '\\', '/'
            $hashRecords.Add("$skillName/$portablePath`:$fileHash")
        }
    }

    $sourceHash = Get-HexDigest -Text (($hashRecords | Sort-Object) -join "`n")
    $manifest = Get-Content -LiteralPath $manifestTemplatePath -Raw | ConvertFrom-Json
    $manifest.version = $version
    $manifest | Add-Member -NotePropertyName metadata -NotePropertyValue @{
        sourceCommit = $sourceCommit
        sourceHash = $sourceHash
        builtAt = $builtAt.ToString('o')
    } -Force
    $manifestOutputPath = Join-Path (Join-Path $pluginRoot '.claude-plugin') 'plugin.json'
    $manifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $manifestOutputPath -Encoding utf8

    if (-not $SkipClaudeValidation) {
        $claude = Get-Command claude -ErrorAction SilentlyContinue
        if ($null -ne $claude) {
            & $claude.Source plugin validate $pluginRoot --strict
            if ($LASTEXITCODE -ne 0) { throw "Claude plugin validation failed for $pluginRoot" }
            $validatedWithClaude = $true
        }
        else {
            Write-Warning 'Claude CLI was not found. Structural ZIP checks will still run; install Claude Code to enable strict plugin validation.'
        }
    }

    $zipName = '{0}-claude-plugin-{1}.zip' -f $PluginName, $version
    $zipPath = Join-Path $OutputDirectory $zipName
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($tempRoot, $zipPath, [System.IO.Compression.CompressionLevel]::Optimal, $false)

    $archive = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $entries = @($archive.Entries | ForEach-Object { $_.FullName })
        $requiredEntries = @("$PluginName/.claude-plugin/plugin.json") + @(
            $skillNames | ForEach-Object { "$PluginName/skills/$_/SKILL.md" }
        )
        foreach ($requiredEntry in $requiredEntries) {
            if ($entries -notcontains $requiredEntry) {
                throw "ZIP verification failed. Missing entry: $requiredEntry"
            }
        }
    }
    finally { $archive.Dispose() }

    $stagingPath = $null
    if ($KeepStaging) {
        $stagingPath = Join-Path $OutputDirectory ("{0}-build-{1}" -f $PluginName, $version)
        if (Test-Path -LiteralPath $stagingPath) { Remove-Item -LiteralPath $stagingPath -Recurse -Force }
        Copy-Item -LiteralPath $tempRoot -Destination $stagingPath -Recurse
    }

    [pscustomobject]@{
        Plugin = $PluginName
        Version = $version
        Skills = $skillNames.Count
        SourceRoot = $SkillsRoot
        SourceCommit = $sourceCommit
        SourceHash = $sourceHash
        ClaudeValidated = $validatedWithClaude
        Zip = $zipPath
        Staging = $stagingPath
    }
}
finally {
    if (Test-Path -LiteralPath $tempRoot) { Remove-Item -LiteralPath $tempRoot -Recurse -Force }
}
