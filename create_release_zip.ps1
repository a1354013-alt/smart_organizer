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

$includePaths = @(
    "app.py",
    "core.py",
    "storage.py",
    "logging_config.py",
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

    if ((Get-Item -LiteralPath $src).PSIsContainer) {
        # tests/：只拷貝檔案，排除 tests/_tmp、__pycache__、*.pyc 等臨時輸出
        Get-ChildItem -LiteralPath $src -Recurse -Force -File | ForEach-Object {
            $rel = $_.FullName.Substring($src.Length).TrimStart('\')
            $relNorm = $rel -replace '/', '\'
            # 排除 tests/_tmp、tests/_tmp_write_test 等所有以 `_tmp` 開頭的測試暫存資料夾
            if ($relNorm -match '(^|\\)_tmp[^\\]*(\\|$)') { return }
            if ($relNorm -match '(^|\\)__pycache__(\\|$)') { return }
            if ($_.Name -like '*.pyc' -or $_.Name -like '*.pyo') { return }

            $target = Join-Path $dst $rel
            $targetDir = Split-Path -Parent $target
            if (-not (Test-Path $targetDir)) {
                New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
            }
            Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        }
    } else {
        $targetDir = Split-Path -Parent $dst
        if (-not (Test-Path $targetDir)) {
            New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
        }
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
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
