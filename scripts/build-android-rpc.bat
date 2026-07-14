@echo off
REM ============================================================================
REM  build-android-rpc.bat  --  Cross-compile ggml-rpc-server for Android ARM64.
REM
REM  Produces a self-contained arm64-v8a rpc-server that the Localy Android
REM  worker app bundles (as libggml-rpc-server.so) and runs as a service.
REM
REM  Uses the Android NDK toolchain + the SDK's bundled CMake/Ninja. No MSVC.
REM  Run from the repo root:  scripts\build-android-rpc.bat
REM ============================================================================
setlocal enabledelayedexpansion

set "REPO_ROOT=%~dp0.."
set "SRC=%REPO_ROOT%\backend\vendor\llama.cpp"
set "BUILD=%SRC%\build-android-arm64"
set "OUT=%REPO_ROOT%\android\app\src\main\jniLibs\arm64-v8a"

set "SDK=%LOCALAPPDATA%\Android\Sdk"
set "NDK=%SDK%\ndk\27.1.12297006"
set "CMAKE=%SDK%\cmake\3.22.1\bin\cmake.exe"
set "NINJA=%SDK%\cmake\3.22.1\bin\ninja.exe"
set "TOOLCHAIN=%NDK%\build\cmake\android.toolchain.cmake"

if not exist "%TOOLCHAIN%" ( echo [ERROR] NDK toolchain not found at "%TOOLCHAIN%". & exit /b 1 )
if not exist "%SRC%\CMakeLists.txt" ( echo [ERROR] llama.cpp source not at "%SRC%". Clone it first. & exit /b 1 )

echo [1/3] Configuring (Android arm64-v8a, RPC on, static, CPU only)...
"%CMAKE%" -S "%SRC%" -B "%BUILD%" -G Ninja ^
  -DCMAKE_MAKE_PROGRAM="%NINJA%" ^
  -DCMAKE_TOOLCHAIN_FILE="%TOOLCHAIN%" ^
  -DANDROID_ABI=arm64-v8a ^
  -DANDROID_PLATFORM=android-24 ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DGGML_RPC=ON ^
  -DGGML_NATIVE=OFF ^
  -DGGML_OPENMP=OFF ^
  -DLLAMA_CURL=OFF ^
  -DLLAMA_BUILD_SERVER=OFF ^
  -DLLAMA_BUILD_TESTS=OFF ^
  -DLLAMA_BUILD_EXAMPLES=OFF ^
  -DBUILD_SHARED_LIBS=OFF || ( echo [ERROR] configure failed & exit /b 1 )

echo [2/3] Building ggml-rpc-server for ARM64 (several minutes)...
"%CMAKE%" --build "%BUILD%" --target ggml-rpc-server || ( echo [ERROR] build failed & exit /b 1 )

echo [3/3] Packaging as libggml-rpc-server.so into jniLibs...
if not exist "%OUT%" mkdir "%OUT%"
for /r "%BUILD%" %%G in (ggml-rpc-server) do copy /Y "%%G" "%OUT%\libggml-rpc-server.so" >nul 2>&1

if exist "%OUT%\libggml-rpc-server.so" (
  echo [OK] Android RPC worker binary ready: %OUT%\libggml-rpc-server.so
  exit /b 0
)
echo [ERROR] Expected binary not produced. Check the build log above.
exit /b 1
