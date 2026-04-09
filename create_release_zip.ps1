param(
    [string]$OutputDir = "release",
    [string]$ZipName = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectName = Split-Path -Leaf $projectRoot
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

function Get-ProjectVersion {
    $versionFile = Join-Path $projectRoot "version.py"
    if (-not (Test-Path $versionFile)) {
        return "unknown"
    }
    try {
        $content = Get-Content -LiteralPath $versionFile -Raw
        # Use single-quoted PowerShell string to avoid escaping issues.
        # Match: __version__ = "2.7.5"  or  __version__='2.7.5'
        $m = [regex]::Match($content, '__version__\s*=\s*["'']([^"''\r\n]+)["'']')
        if ($m.Success) {
            return $m.Groups[1].Value
        }
    } catch {
        return "unknown"
    }
    return "unknown"
}

if ([string]::IsNullOrWhiteSpace($ZipName)) {
    # 正式交付為 runtime/demo package（不含 tests），避免把 workspace 快照誤當 release
    $version = Get-ProjectVersion
    $ZipName = "$projectName-v$version-runtime-demo-$timestamp.zip"
}

$outputRoot = Join-Path $projectRoot $OutputDir
$stagingRoot = Join-Path $outputRoot "_staging_$timestamp"
$zipPath = Join-Path $outputRoot $ZipName

$includePaths = @(
    "app.py",
    "core.py",
    "services.py",
    "storage.py",
    "logging_config.py",
    "version.py",
    "contracts.py",
    "README.md",
    "requirements.txt"
)

New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
if (Test-Path $stagingRoot) {
    Remove-Item -LiteralPath $stagingRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null

function Copy-IncludePath {
    param([string]$RelativePath)

    $src = Join-Path $projectRoot $RelativePath
    $dst = Join-Path $stagingRoot $RelativePath

    if (-not (Test-Path $src)) {
        return
    }

    $item = Get-Item -LiteralPath $src
    if ($item.PSIsContainer) {
        throw "Official runtime/demo release must not include directories. Refusing to package folder: $RelativePath"
    }

    $targetDir = Split-Path -Parent $dst
    if (-not (Test-Path $targetDir)) {
        New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
    }
    Copy-Item -LiteralPath $src -Destination $dst -Force
}

foreach ($p in $includePaths) {
    Copy-IncludePath -RelativePath $p
}

if (Test-Path $zipPath) {
    try {
        Remove-Item -LiteralPath $zipPath -Force -ErrorAction Stop
    } catch {
        # 若輸出 zip 被鎖定或權限受限，改用新的檔名避免整體失敗
        $base = [System.IO.Path]::GetFileNameWithoutExtension($ZipName)
        $zipPath = Join-Path $outputRoot ("{0}-{1}.zip" -f $base, $timestamp)
        Write-Warning "Existing zip cannot be removed; writing to new zip: $zipPath - $($_.Exception.Message)"
    }
}

Compress-Archive -Path (Join-Path $stagingRoot '*') -DestinationPath $zipPath -CompressionLevel Optimal
try {
    Remove-Item -LiteralPath $stagingRoot -Recurse -Force -ErrorAction Stop
} catch {
    # 在某些受限環境（例如被鎖定的檔案/權限限制）可能無法刪除 staging，
    # 但 release zip 已經生成，這裡改為警告而非整體失敗。
    Write-Warning "Cleanup staging failed: $stagingRoot - $($_.Exception.Message)"
}

Write-Output "Release zip created: $zipPath"
