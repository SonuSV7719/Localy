@echo off
REM ============================================================================
REM  build-backend-exe.bat -- Bundle the Localy backend into a standalone .exe
REM  via PyInstaller, so the desktop app can ship it as a sidecar (no Python on
REM  the target machine). Output is copied to the Tauri sidecar location with
REM  the target-triple name Tauri expects.
REM  Run from repo root:  scripts\build-backend-exe.bat
REM ============================================================================
setlocal
set "REPO=%~dp0.."
set "BACKEND=%REPO%\backend"
set "PY=%BACKEND%\.venv\Scripts\python.exe"
set "ENTRY=%BACKEND%\packaging\localy_backend.py"
set "DIST=%BACKEND%\packaging\dist"
set "WORK=%BACKEND%\packaging\build"
REM Tauri sidecar target-triple name for Windows x64:
set "TRIPLE=x86_64-pc-windows-msvc"
set "SIDEDIR=%REPO%\desktop\src-tauri\binaries"

if not exist "%PY%" ( echo [ERROR] venv python not found at %PY% & exit /b 1 )

echo [1/2] Running PyInstaller (bundling llama_cpp native libs)...
"%PY%" -m PyInstaller ^
  --noconfirm --clean --onedir --name localy-backend ^
  --distpath "%DIST%" --workpath "%WORK%" --specpath "%BACKEND%\packaging" ^
  --collect-all llama_cpp ^
  --collect-submodules localy ^
  --collect-all zeroconf ^
  --collect-all ifaddr ^
  --collect-submodules uvicorn ^
  --hidden-import uvicorn.logging ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.lifespan.on ^
  --hidden-import cpufeature ^
  "%ENTRY%" || ( echo [ERROR] PyInstaller failed & exit /b 1 )

echo [2/2] Copying bundle into the Tauri sidecar location...
if not exist "%SIDEDIR%" mkdir "%SIDEDIR%"
REM onedir output: dist\localy-backend\  (exe + _internal deps). Ship the folder
REM as a Tauri resource and the exe as the triple-named sidecar entry.
if exist "%DIST%\localy-backend\localy-backend.exe" (
  copy /Y "%DIST%\localy-backend\localy-backend.exe" "%SIDEDIR%\localy-backend-%TRIPLE%.exe" >nul
  echo [OK] Backend bundle at %DIST%\localy-backend  (exe copied to %SIDEDIR%)
  exit /b 0
)
echo [ERROR] Expected exe not produced.
exit /b 1
