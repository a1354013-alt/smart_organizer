param(
    [string]$OutputDir = "release",
    [string]$ZipName = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectName = Split-Path -Leaf $projectRoot
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

if ([string]::IsNullOrWhiteSpace($ZipName)) {
    $ZipName = "$projectName-release-$timestamp.zip"
}

$outputRoot = Join-Path $projectRoot $OutputDir
$stagingRoot = Join-Path $outputRoot "_staging_$timestamp"
$zipPath = Join-Path $outputRoot $ZipName

$excludedDirNames = @(
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "build",
    "dist",
    "release",
    "uploads",
    "repo",
    "repo_v1",
    "test_uploads",
    "test_repo",
    "node_modules"
)

$excludedPathPatterns = @(
    "smart_org_regression_*",
    "tests\_tmp*",
    "frontend\node_modules*"
)

$excludedFilePatterns = @(
    "*.pyc",
    "*.pyo",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.log",
    "*.zip"
)

New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
if (Test-Path $stagingRoot) {
    Remove-Item -LiteralPath $stagingRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null

function Test-ExcludedPath {
    param([string]$RelativePath, [bool]$IsDirectory)

    $normalized = $RelativePath -replace '/', '\'
    $segments = $normalized.Split('\') | Where-Object { $_ }

    foreach ($segment in $segments) {
        if ($excludedDirNames -contains $segment) {
            return $true
        }
    }

    foreach ($pattern in $excludedPathPatterns) {
        if ($normalized -like $pattern) {
            return $true
        }
    }

    if (-not $IsDirectory) {
        foreach ($pattern in $excludedFilePatterns) {
            if ((Split-Path $normalized -Leaf) -like $pattern) {
                return $true
            }
        }
    }

    return $false
}

Get-ChildItem -LiteralPath $projectRoot -Recurse -Force | ForEach-Object {
    $sourcePath = $_.FullName
    if ($sourcePath -eq $outputRoot -or $sourcePath.StartsWith($outputRoot + [IO.Path]::DirectorySeparatorChar)) {
        return
    }

    $relativePath = $sourcePath.Substring($projectRoot.Length).TrimStart('\')
    if ([string]::IsNullOrWhiteSpace($relativePath)) {
        return
    }

    if (Test-ExcludedPath -RelativePath $relativePath -IsDirectory $_.PSIsContainer) {
        return
    }

    $targetPath = Join-Path $stagingRoot $relativePath
    if ($_.PSIsContainer) {
        New-Item -ItemType Directory -Force -Path $targetPath | Out-Null
    } else {
        $targetDir = Split-Path -Parent $targetPath
        if (-not (Test-Path $targetDir)) {
            New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
        }
        Copy-Item -LiteralPath $sourcePath -Destination $targetPath -Force
    }
}

if (Test-Path $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

Compress-Archive -Path (Join-Path $stagingRoot '*') -DestinationPath $zipPath -CompressionLevel Optimal
Remove-Item -LiteralPath $stagingRoot -Recurse -Force

Write-Output "Release zip created: $zipPath"
