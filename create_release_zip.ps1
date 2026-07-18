param(
    [string]$OutputDir = "release_ci",
    [string]$ZipName = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonScript = Join-Path $projectRoot "scripts\create_release_zip.py"

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

$args = @("-B", $pythonScript, "--output-dir", $OutputDir)
if (-not [string]::IsNullOrWhiteSpace($ZipName)) {
    $args += @("--zip-name", $ZipName)
}

# Packaging policy lives in scripts/create_release_zip.py only.
& $python @args
