# package-sidecar.ps1
# Packages the Localy backend into the Tauri resource folder used at runtime.

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
$BuildScript = Join-Path $ProjectRoot "scripts\build-backend-exe.bat"

if (-not (Test-Path $BuildScript)) {
    throw "Backend build script not found: $BuildScript"
}

Write-Host "Packaging Localy backend resource..." -ForegroundColor Cyan
& $BuildScript

if ($LASTEXITCODE -ne 0) {
    throw "Backend packaging failed with exit code $LASTEXITCODE"
}

Write-Host "Backend resource packaging completed." -ForegroundColor Green
