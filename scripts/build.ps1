# build.ps1
# Automates the full production build pipeline: Python PyInstaller compile -> Tauri Windows bundler.

$ErrorActionPreference = "Stop"

Write-Host "🏗️ Starting Full Localy Production Build..." -ForegroundColor Cyan

# Define paths
$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
$ScriptsDir = "$ProjectRoot\scripts"
$DesktopDir = "$ProjectRoot\desktop"

# 1. Package Python sidecar backend
Write-Host "📦 1/3 Compiling Python Backend Executable..." -ForegroundColor Yellow
& "$ScriptsDir\package-sidecar.ps1"

# 2. Install Node dependencies
Write-Host "📦 2/3 Installing Frontend Dependencies..." -ForegroundColor Yellow
Push-Location $DesktopDir
try {
    npm install
}
finally {
    Pop-Location
}

# 3. Build Tauri production bundles
Write-Host "📦 3/3 Running Tauri Bundle Packager..." -ForegroundColor Yellow
Push-Location $DesktopDir
try {
    npm run tauri build
    Write-Host "🎉 Localy production builds completed successfully!" -ForegroundColor Green
}
catch {
    Write-Error "❌ Production build failed: $_"
}
finally {
    Pop-Location
}
