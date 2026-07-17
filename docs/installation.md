# Installation

Localy can be installed two ways:

1. **[Desktop app](#option-1-desktop-app-recommended)** — a one-click Windows installer with the backend bundled (no Python needed). Best for most people.
2. **[From source](#option-2-from-source)** — run the Python backend and/or build the desktop app yourself. Best for developers and non-Windows users who want the CLI/API.

---

## Option 1: Desktop app (recommended)

### Requirements

- Windows 10 or 11 (64-bit)
- ~500 MB free disk for the app, plus space for the models you download (a 7B Q4 model is ~4–5 GB)
- 16 GB RAM recommended for 7B-class models

### Install

1. Download the latest **`Localy_<version>_x64-setup.exe`** from the [Releases page](https://github.com/SonuSV7719/Localy/releases).
2. Run the installer and follow the prompts.
3. Launch **Localy** from the Start menu.

The bundled backend starts automatically in the background — there is **nothing else to install**. On first launch you'll be guided through a quick hardware probe, then you can download a model and start chatting. See the [User Guide](user-guide.md).

### Uninstall

Uninstall "Localy" from **Settings → Apps** (or the Start-menu uninstaller). Downloaded models and chat history live in your user data directory (see [Configuration → Storage](configuration.md#storage-locations)) and can be removed separately.

---

## Option 2: From source

### Backend (CLI + REST API)

Requires **Python 3.12+** and **[uv](https://github.com/astral-sh/uv)**.

```bash
git clone https://github.com/SonuSV7719/Localy.git
cd Localy/backend

pip install uv        # if you don't already have uv
uv sync               # creates .venv and installs dependencies

uv run localy probe   # verify it detects your hardware
uv run localy serve   # start the API on http://127.0.0.1:11434
```

That's enough to use the CLI and the REST API. See the [Development Guide](development-guide.md) for the full command list and tests.

### Desktop app (dev mode)

Requires the backend prerequisites above, plus **Node.js 18+** and the **[Rust toolchain](https://rustup.rs/)** (for Tauri).

```bash
cd Localy/desktop
npm install
npm run tauri dev     # launches the app against the local backend
```

> In dev mode the app expects a backend to be reachable at `http://127.0.0.1:11434`.
> Either run `uv run localy serve` in the `backend/` directory first, or rely on the
> bundled sidecar in a production build.

### Build the desktop installer

To produce the `Localy_<version>_x64-setup.exe` NSIS installer with the backend bundled:

```bash
# 1. Build the backend into a standalone executable (PyInstaller) and stage
#    the RPC binaries — see scripts/ for the helper scripts.
# 2. Build the Tauri app + installer:
cd Localy/desktop
npm run tauri build
```

The installer is written to `desktop/src-tauri/target/release/bundle/nsis/`.

> Building the installer bundles the PyInstaller backend and the llama.cpp RPC
> binaries as Tauri resources. If device pooling matters to you, build the RPC
> binaries first (`scripts/build-llama-rpc`) so they're included.

---

## Verifying the install

- **Desktop app:** the status dot in the bottom-left of the sidebar should read **"Backend Online"** (green) within a few seconds of launch.
- **CLI/API:** `curl http://127.0.0.1:11434/health` should return `{"status":"ok"}`.

If it doesn't, see [Troubleshooting](troubleshooting.md).

## Next steps

- [User Guide](user-guide.md) — download a model and start chatting
- [Device Pooling](device-pooling.md) — combine devices for bigger models
- [Configuration](configuration.md) — change ports, storage, and API keys
