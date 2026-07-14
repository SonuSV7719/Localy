# dev.ps1
# Runs both the FastAPI backend and Tauri desktop app concurrently in development mode.

$ErrorActionPreference = "Stop"

Write-Host "🚀 Launching Localy in Development Mode..." -ForegroundColor Cyan

# Define paths
$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
$BackendDir = "$ProjectRoot\backend"
$DesktopDir = "$ProjectRoot\desktop"

# 1. Start Python Backend in a separate window (hot-reloading enabled)
Write-Host "🌐 Launching FastAPI Backend Server..." -ForegroundColor Yellow
$BackendArgs = @(
    "-NoExit",
    "-Command",
    "cd '$BackendDir'; uv run --no-project uvicorn localy.main:create_app --factory --reload --port 11434 --host 127.0.0.1"
)
Start-Process powershell -ArgumentList $BackendArgs

# 2. Wait for backend to warm up
Write-Host "⏳ Waiting for API health check..." -ForegroundColor Yellow
$MaxRetries = 15
$Retries = 0
$BackendUp = $false

while (-not $BackendUp -and $Retries -lt $MaxRetries) {
    try {
        $Response = Invoke-WebRequest -Uri "http://127.0.0.1:11434/health" -Method Get -TimeoutSec 1 -UseBasicParsing
        if ($Response.StatusCode -eq 200) {
            $BackendUp = $true
        }
    }
    catch {
        Start-Sleep -Seconds 1
        $Retries++
    }
}

if (-not $BackendUp) {
    Write-Warning "⚠️ Backend did not respond to health checks. Trying to continue launching Tauri anyway..."
} else {
    Write-Host "✅ Backend is healthy and listening on http://127.0.0.1:11434" -ForegroundColor Green
}

# 3. Start Tauri development server
Write-Host "🖥️ Launching Tauri Desktop Dev Server..." -ForegroundColor Yellow
Push-Location $DesktopDir
try {
    npm run tauri dev
}
finally {
    Pop-Location
}
