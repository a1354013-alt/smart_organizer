param(
    [string]$OutputDir = "release",
    [string]$ZipName = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonScript = Join-Path $projectRoot "scripts\create_release_zip.py"

function Get-ProjectVersion {
    $versionFile = Join-Path $projectRoot "version.py"
    if (-not (Test-Path $versionFile)) {
        return "unknown"
    }
    $content = Get-Content -LiteralPath $versionFile -Raw
    $m = [regex]::Match($content, '__version__\s*=\s*["'']([^"''\r\n]+)["'']')
    if ($m.Success) {
        return $m.Groups[1].Value
    }
    return "unknown"
}

# Official runtime/demo allowlist. Keep this synced with scripts/create_release_zip.py,
# README.md, RELEASE_PACKAGING.md, RUN_RELEASE.md, and tests.
$includePaths = @(
    "app.py",
    "app_main.py",
    "core.py",
    "core_utils.py",
    "core_classification.py",
    "core_processor.py",
    "services.py",
    "services_models.py",
    "services_analysis.py",
    "services_review.py",
    "services_finalize.py",
    "storage.py",
    "storage_base.py",
    "storage_schema.py",
    "storage_repository.py",
    "storage_recovery.py",
    "storage_search.py",
    "storage_cleanup.py",
    "storage_manager.py",
    "ui_common.py",
    "ui_state.py",
    "ui_home.py",
    "ui_upload.py",
    "ui_review.py",
    "ui_execute.py",
    "ui_search.py",
    "ui_records.py",
    "ui_renderers.py",
    "requirements.txt",
    "README.md",
    "RELEASE_PACKAGING.md",
    "RUN_RELEASE.md",
    "async_processor.py",
    "contracts.py",
    "frontend_safety.py",
    "logging_config.py",
    "version.py"
)

if (-not (Test-Path $pythonScript)) {
    throw "Packaging helper not found: $pythonScript"
}

$python = if (Get-Command python -ErrorAction SilentlyContinue) {
    "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    "py"
} else {
    throw "Python is required to build the release zip."
}

$args = @($pythonScript, "--output-dir", $OutputDir)
if (-not [string]::IsNullOrWhiteSpace($ZipName)) {
    $args += @("--zip-name", $ZipName)
}

& $python @args
