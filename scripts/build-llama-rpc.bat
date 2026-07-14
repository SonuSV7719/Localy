@echo off
REM ============================================================================
REM  build-llama-rpc.bat  --  Build llama.cpp with the RPC backend enabled.
REM
REM  Produces rpc-server.exe + llama-server.exe (RPC-capable) used by Localy's
REM  Phase 3 device pooling. RPC is NOT in any prebuilt release, so we compile
REM  it here with -DGGML_RPC=ON using the Visual Studio 2022 toolchain.
REM
REM  Output binaries are copied to  backend\vendor\llama-rpc\
REM  Run from the repo root:  scripts\build-llama-rpc.bat
REM ============================================================================
setlocal enabledelayedexpansion

set "REPO_ROOT=%~dp0.."
set "SRC=%REPO_ROOT%\backend\vendor\llama.cpp"
set "BUILD=%SRC%\build-rpc"
set "OUT=%REPO_ROOT%\backend\vendor\llama-rpc"

REM --- Locate and activate the MSVC build environment -----------------------
set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VCVARS%" (
  echo [ERROR] vcvars64.bat not found at "%VCVARS%".
  echo         Install the "Desktop development with C++" workload in Visual Studio 2022.
  exit /b 1
)
echo [1/4] Activating MSVC x64 environment...
call "%VCVARS%" >nul || (echo [ERROR] Failed to run vcvars64.bat & exit /b 1)

if not exist "%SRC%\CMakeLists.txt" (
  echo [ERROR] llama.cpp source not found at "%SRC%".
  echo         Run: git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "%SRC%"
  exit /b 1
)

REM --- Configure: CPU backend + RPC + server, no CUDA -----------------------
echo [2/4] Configuring CMake (RPC on, CPU only)...
cmake -S "%SRC%" -B "%BUILD%" -G Ninja ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DGGML_RPC=ON ^
  -DLLAMA_BUILD_SERVER=ON ^
  -DLLAMA_CURL=OFF ^
  -DGGML_NATIVE=ON ^
  -DBUILD_SHARED_LIBS=ON || (echo [ERROR] CMake configure failed & exit /b 1)

REM --- Build only the targets we need ---------------------------------------
echo [3/4] Building ggml-rpc-server + llama-server (this takes several minutes)...
cmake --build "%BUILD%" --config Release --target ggml-rpc-server llama-server || (echo [ERROR] Build failed & exit /b 1)

REM --- Collect the outputs --------------------------------------------------
echo [4/4] Collecting binaries into "%OUT%"...
if not exist "%OUT%" mkdir "%OUT%"
for %%F in (ggml-rpc-server.exe llama-server.exe) do (
  for /r "%BUILD%" %%G in (%%F) do copy /Y "%%G" "%OUT%\" >nul 2>&1
)
REM Copy the runtime DLLs (ggml, llama) next to the exes.
for /r "%BUILD%" %%G in (*.dll) do copy /Y "%%G" "%OUT%\" >nul 2>&1

echo.
if exist "%OUT%\ggml-rpc-server.exe" if exist "%OUT%\llama-server.exe" (
  echo [OK] Build complete. Binaries in: %OUT%
  dir /b "%OUT%\*.exe"
  exit /b 0
)
echo [ERROR] Expected binaries were not produced. Check the build log above.
exit /b 1
