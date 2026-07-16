# Localy Developer Guide

Welcome to the development guide for Localy. This guide explains how to set up the development environment, execute CLI tasks, run the test suite, and follow coding guidelines.

---

## 1. Development Environment Setup

Localy uses **`uv`** as its Python package and workspace manager for extremely fast, reproducible environments.

### Prerequisites
- Python 3.12 or higher installed on your system.
- `uv` installed (install via `pip install uv` or following the official guide).

### Setup Steps
1. Navigate to the backend directory:
   ```powershell
   cd C:\My_Project\Localy\backend
   ```
2. Sync the project dependencies:
   ```powershell
   uv sync
   ```
   This will automatically create a `.venv` virtual environment in the `backend/` directory, configure type annotations, and download all target requirements.

---

## 2. Directory Layout & CLI Commands

Localy is structured cleanly as a single-package python codebase:
- `backend/src/localy/` contains all source code.
- `backend/tests/` contains unit and integration tests.

### Running CLI Commands
During development, you can run all commands directly in the shell prefixing with `uv run localy`:

```powershell
# Probe the host system hardware
uv run localy probe

# Display the registry model list alongside hardware-fit evaluations
uv run localy models

# Force check model compatibility advisor
uv run localy fit smollm2:2b

# Download a model from the registry (performs pre-flight fit checks)
uv run localy pull smollm2:2b

# Launch interactive chat session in the console (applies auto-tuning)
uv run localy run smollm2:2b

# Run standard generation benchmark (optional compare against Ollama)
uv run localy benchmark smollm2:2b

# Start the local FastAPI server (OpenAI + Ollama APIs)
uv run localy serve
```

---

## 2b. Building Native Binaries & the Installer

Some features need binaries compiled from source (they are not on PyPI / not
shippable prebuilt). All scripts run from the **repo root**; outputs are
gitignored and regenerated on demand.

| Script | Produces | Needs |
|---|---|---|
| `scripts\build-llama-rpc.bat` | `backend/vendor/llama-rpc/` — RPC-enabled `ggml-rpc-server` + `llama-server` (for device pooling) | VS 2022 C++ toolchain (bundled MSVC/CMake/Ninja) |
| `scripts\build-android-rpc.bat` | `android/.../jniLibs/arm64-v8a/libggml-rpc-server.so` (the Android worker's native binary) | Android NDK (r27) |
| `scripts\build-backend-exe.bat` | `backend/packaging/dist/localy-backend/` — the backend bundled with PyInstaller (no Python needed on target) | PyInstaller in the venv |

**Full Windows installer** (bundles the backend + RPC binaries + `cloudflared`):

```powershell
# 1. Build the RPC binaries and the backend exe (once / when backend changes)
scripts\build-llama-rpc.bat
scripts\build-backend-exe.bat
# 2. Copy into Tauri resources, then build the NSIS installer
#    (resources: desktop/src-tauri/resources/{backend,llama-rpc})
cd desktop
npx tauri build --bundles nsis
# -> desktop/src-tauri/target/release/bundle/nsis/Localy_0.1.0_x64-setup.exe
```

The Android worker APK is built from `android/` (`./gradlew :app:assembleDebug`)
— see `android/README.md`.

> **CPU note:** use the AVX2 `llama-cpp-python` wheel (CPU index), not the
> default one — the default requires AVX-512 and crashes with an illegal
> instruction on 12th-gen Intel and other AVX2-only CPUs.

---

## 3. Running Tests

To avoid rebuilding the project wheel during development cycles, run tests directly using python with the `src` directory inserted into `sys.path`.

### Run the full test suite
Execute this command from the `backend/` directory:
```powershell
uv run --no-project python -c "import sys; sys.path.insert(0, 'src'); import pytest; sys.exit(pytest.main(['tests']))"
```

### Run specific test files
```powershell
# Run only E2E tests
uv run --no-project python -c "import sys; sys.path.insert(0, 'src'); import pytest; sys.exit(pytest.main(['tests/test_e2e.py']))"

# Run only tuning unit tests
uv run --no-project python -c "import sys; sys.path.insert(0, 'src'); import pytest; sys.exit(pytest.main(['tests/test_optimizer.py']))"
```

---

## 4. Code Quality & Standards

We enforce strict linting, formatting, and static typing rules:

### Formatting & Linting (Ruff)
Ruff is configured in `pyproject.toml` to lint and format code. Run the following checks before committing code:
```powershell
# Lint check
uv run ruff check src tests

# Auto-format files
uv run ruff format src tests
```

### Static Type Analysis (Mypy)
Mypy validates type safety configurations:
```powershell
uv run mypy src
```

---

## 5. Development Guidelines & Best Practices

1. **Keep Imports Dynamic When Heavy**:
   Modules like `llama_cpp` are heavy and might take hundreds of milliseconds to import. To keep CLI command responsiveness instantaneous (under 50ms startup), delay importing heavy packages until they are explicitly needed in target function scopes.
2. **Access Control**:
   The API server binds `0.0.0.0` so LAN/tunnel clients can reach it, but every
   non-loopback request is gated by an API key (fail-closed). Any new endpoint
   must apply `verify_api_key` (or `require_local` for management actions), and
   must treat proxied requests (`X-Forwarded-For`/`Cf-Connecting-Ip`) as remote
   so tunnels can't bypass auth. The RPC worker (`ggml-rpc-server`) is LAN-only
   and insecure by design — never expose it directly to the internet.
3. **Mocks & Hardware Reports**:
   When writing tests that execute engine code or hardware probes, always mock dependencies to prevent multi-gigabyte downloads or platform-specific OS errors on execution targets.
