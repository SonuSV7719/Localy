@echo off
REM ============================================================================
REM  build-backend-exe.bat -- Bundle the Localy backend into a standalone .exe
REM  via PyInstaller, so the desktop app can ship it as a sidecar (no Python on
REM  the target machine). Output is copied to the Tauri resource folder that
REM  desktop/src-tauri/src/sidecar.rs launches at runtime.
REM  Run from repo root:  scripts\build-backend-exe.bat
REM ============================================================================
setlocal
set "REPO=%~dp0.."
set "BACKEND=%REPO%\backend"
set "PY=%BACKEND%\.venv\Scripts\python.exe"
set "ENTRY=%BACKEND%\packaging\localy_backend.py"
set "DIST=%BACKEND%\packaging\dist"
set "WORK=%BACKEND%\packaging\build"
set "RESOURCEDIR=%REPO%\desktop\src-tauri\resources\backend"

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
  --collect-all pypdf ^
  --collect-all multipart ^
  --collect-all python_multipart ^
  --collect-all huggingface_hub ^
  --hidden-import uvicorn.logging ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.lifespan.on ^
  --hidden-import cpufeature ^
  --hidden-import multipart ^
  --hidden-import python_multipart ^
  "%ENTRY%" || ( echo [ERROR] PyInstaller failed & exit /b 1 )

echo [2/2] Copying bundle into the Tauri resource folder...
if exist "%RESOURCEDIR%" rmdir /S /Q "%RESOURCEDIR%"
if exist "%DIST%\localy-backend\localy-backend.exe" (
  xcopy /E /I /Y "%DIST%\localy-backend" "%RESOURCEDIR%" >nul
  echo [OK] Backend resource refreshed at %RESOURCEDIR%
  exit /b 0
)
echo [ERROR] Expected exe not produced.
exit /b 1
