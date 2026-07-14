# package-sidecar.ps1
# Packages the Localy python backend as a Tauri sidecar using PyInstaller.

$ErrorActionPreference = "Stop"

Write-Host "📦 Starting Localy Backend Sidecar Packaging..." -ForegroundColor Cyan

# Define paths
$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
$BackendDir = "$ProjectRoot\backend"
$DesktopDir = "$ProjectRoot\desktop"
$BinariesDir = "$DesktopDir\src-tauri\binaries"

# 1. Ensure output binaries directory exists
if (-not (Test-Path $BinariesDir)) {
    Write-Host "📁 Creating binaries output directory: $BinariesDir" -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path $BinariesDir | Out-Null
}

# 2. Package the backend CLI using PyInstaller via uv
Write-Host "🔨 Compiling standalone executable..." -ForegroundColor Yellow
Push-Location $BackendDir

try {
    # Run PyInstaller on a single line to avoid backtick continuation issues
    uv run --no-project pyinstaller src/localy/cli/main.py --onefile --name "localy-backend-x86_64-pc-windows-msvc" --paths "src" --collect-all "llama_cpp" --collect-all "uvicorn" --collect-all "fastapi" --clean --distpath "$BinariesDir" --workpath "build" --specpath "build"

    Write-Host "✅ Standalone backend executable compiled successfully!" -ForegroundColor Green
    Write-Host "📍 Location: $BinariesDir\localy-backend-x86_64-pc-windows-msvc.exe" -ForegroundColor Green
}
catch {
    Write-Error "❌ Failed to package sidecar: $_"
}
finally {
    Pop-Location
}
