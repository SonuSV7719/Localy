<div align="center">

<img src="desktop/src-tauri/icons/128x128.png" alt="Localy logo" width="96" />

# Localy

**Run open-source LLMs on your own devices — auto-tuned, honest about what fits, and poolable across machines.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/desktop-Windows-0078D6.svg)](docs/installation.md)
[![Backend](https://img.shields.io/badge/backend-Python%203.12%2B-3776AB.svg)](backend)
[![Desktop](https://img.shields.io/badge/desktop-Tauri%202%20%2B%20React-24C8DB.svg)](desktop)
[![API](https://img.shields.io/badge/API-OpenAI%20%2B%20Ollama%20compatible-412991.svg)](docs/api-reference.md)

[Install](docs/installation.md) · [User Guide](docs/user-guide.md) · [Device Pooling](docs/device-pooling.md) · [API Reference](docs/api-reference.md) · [Architecture](docs/architecture.md) · [Troubleshooting](docs/troubleshooting.md)

</div>

---

## Table of Contents

- [What is Localy](#what-is-localy)
- [Why Localy](#why-localy)
- [Features](#features)
- [Quick Start](#quick-start)
  - [Desktop app](#desktop-app-recommended)
  - [CLI / backend](#cli--backend)
- [Device Pooling in 60 seconds](#device-pooling-in-60-seconds)
- [API Compatibility](#api-compatibility)
- [Architecture](#architecture)
- [Project Status](#project-status)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## What is Localy

Localy is a local LLM platform that wraps [`llama.cpp`](https://github.com/ggerganov/llama.cpp) and adds the parts that are usually missing: it **auto-detects your hardware** (P-cores vs E-cores, RAM, GPU, SIMD), **tunes inference** for that machine, tells you **honestly whether a model will fit before you download it**, and lets you **pool several devices** to run models that are too big for any single one.

It ships as a **desktop app** (one-click Windows installer, no Python required) and a **CLI/REST server** that speaks both the **OpenAI** and **Ollama** APIs, so existing tools point at it unchanged.

## Why Localy

| | Ollama / LM Studio | **Localy** |
|---|---|---|
| Thread configuration | Generic defaults | Auto-tuned from your actual CPU topology |
| "Will this model fit?" | Download and find out | **Pre-download fit check** with honest recommendations |
| Performance expectation | No prediction | First-run **benchmark** reports real tok/s |
| Bigger-than-one-machine models | Single device only | **Pool devices** over WiFi/hotspot |
| Sharing access | Manual | Built-in API keys + optional internet tunnel |

> **Honest promise:** the best speed for what your machine can hold, and a real path to bigger models via pooling.
> **Not promised:** "any model at full speed on any hardware" — that's physically impossible, and we won't pretend otherwise.

## Features

- **🖥 Desktop app** (Tauri 2 + React) — guided onboarding, streaming chat, model catalog, device pool, and API access, in one window.
- **💬 Rich chat** — Markdown rendering with copyable code blocks, collapsible model **reasoning** (`<think>`), stop-generation, and conversation **delete / archive / rename**. Long histories are quota-safe.
- **🧠 Auto-tuning** — threads, batch size, and mmap chosen from your live hardware, not generic presets.
- **📊 Honest fit advising** — every model shows *fits well / tight / does not fit* before download, with the reason.
- **📁 Dynamic model catalog** — quantization variants pulled live from Hugging Face with real sizes; search and add any GGUF repo.
- **⬇️ Background downloads** — parallel, resumable, atomic; survive tab switches with live speed/ETA and cancel.
- **🔗 Device pooling** — split a model's layers across any number of devices on the same WiFi/hotspot ([llama.cpp RPC](https://github.com/ggerganov/llama.cpp/tree/master/tools/rpc)), weighted by each device's memory and speed. Includes a zero-setup **Android worker**. See [who computes what, live](docs/device-pooling.md#live-contribution-analysis).
- **🔌 API access** — OpenAI-compatible endpoint for other apps/people: generate API keys, expose on the LAN, or over the internet via a Cloudflare tunnel (fail-closed auth).
- **⚙️ Background / daemon mode** — opt-in autostart-on-login and close-to-tray, so the server keeps serving after you close the window. Stop it from the tray any time.

## Quick Start

### Desktop app (recommended)

1. Download the latest **`Localy_<version>_x64-setup.exe`** from [Releases](https://github.com/SonuSV7719/Localy/releases) (or [build it](docs/installation.md#build-the-desktop-installer)).
2. Run the installer and launch **Localy**. The backend is bundled — **no Python needed**.
3. Complete the one-time hardware probe, download a model from the **Model Catalog**, and start chatting.

Full walkthrough: **[User Guide](docs/user-guide.md)**.

### CLI / backend

Requires [Python 3.12+](https://www.python.org/) and [`uv`](https://github.com/astral-sh/uv).

```bash
cd backend
pip install uv          # if you don't have it
uv sync                 # create the environment

uv run localy probe             # detect your hardware
uv run localy models            # list models with fit assessment
uv run localy pull llama3.1:8b  # download (checks fit first)
uv run localy run  llama3.1:8b  # interactive chat
uv run localy serve             # start the REST API (OpenAI + Ollama)
```

| Command | Description |
|---|---|
| `localy probe` | Detect and display hardware capabilities |
| `localy models` | List available models with fit assessment |
| `localy fit <model>` | Detailed hardware fit check |
| `localy pull <model>` | Download a model from the registry |
| `localy run <model>` | Interactive chat with auto-tuned inference |
| `localy benchmark <model>` | Performance benchmark (reports tok/s) |
| `localy serve` | Start the REST API server (default `:11434`) |

## Device Pooling in 60 seconds

Pooling combines devices to run a model **too big for one machine**. Joining a device makes it *available* — you then load a model across the pool in one click.

1. **On each helper device:** open Localy → **Device Pool** → **🤝 Share this device**.
2. **On your main device:** **Device Pool** → **🔍 Scan** (or add `host:port`) → **Join**.
3. Pick a model → **Run pooled**. This splits the model across the devices.
4. **Chat as normal** — that model is now served across the pool, and the **Live Contribution** panel shows each device's layer share.

> ⚠️ Joining alone does **not** start using a device — you must click **Run pooled** once. And pooling unlocks *bigger* models; a model that already fits on one device runs faster solo. Full guide: **[Device Pooling](docs/device-pooling.md)**.

## API Compatibility

Localy serves at `http://127.0.0.1:11434` and accepts both OpenAI and Ollama payloads:

```bash
# OpenAI-compatible
curl http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "llama3.1:8b", "messages": [{"role": "user", "content": "Hello"}]}'

# Ollama-compatible
curl http://localhost:11434/api/chat \
  -d '{"model": "llama3.1:8b", "messages": [{"role": "user", "content": "Hello"}]}'
```

Point Continue, LibreChat, or any OpenAI SDK at that URL. LAN/internet requests require an API key (loopback is always allowed). See the full **[API Reference](docs/api-reference.md)**.

## Architecture

```
User → CLI / Desktop App → FastAPI Server → llama-cpp-python → llama.cpp
          ↕                     ↕                   ↕
   Hardware Probe   Auto-Tuning Engine     RPC Coordinator → pooled devices
```

Localy does **not** reimplement inference — it orchestrates `llama.cpp` and adds live auto-tuning, honest fit advising, a curated + dynamic model registry, and cross-device pooling. Deep dive: **[Architecture](docs/architecture.md)**.

## Project Status

| Phase | Scope | Status |
|---|---|---|
| **1** | Speed engine — auto-tuned single-machine inference | ✅ |
| **2** | Desktop app — chat, catalog, one-click installer | ✅ |
| **3** | Device pooling — LAN/hotspot, bigger models | ✅ |
| **4** | Internet pooling — friends-only, then open network | 🔬 scoping |

See [docs/vision-and-roadmap.md](docs/vision-and-roadmap.md) for the full pooling vision and the honest "why pooling ≠ faster" reasoning.

## Documentation

| Guide | For |
|---|---|
| [Installation](docs/installation.md) | Install the app or build from source |
| [User Guide](docs/user-guide.md) | Using chat, models, API access, settings |
| [Device Pooling](docs/device-pooling.md) | Combine devices for bigger models |
| [Configuration](docs/configuration.md) | Ports, env vars, storage, API keys |
| [API Reference](docs/api-reference.md) | OpenAI + Ollama endpoints |
| [Architecture](docs/architecture.md) | How the system fits together |
| [Development Guide](docs/development-guide.md) | Set up a dev environment, run tests |
| [Troubleshooting](docs/troubleshooting.md) | Fixes for common issues |
| [Vision & Roadmap](docs/vision-and-roadmap.md) | Where Localy is heading |

## Contributing

Contributions are welcome. Please read **[CONTRIBUTING.md](CONTRIBUTING.md)** and the [Development Guide](docs/development-guide.md) first. All changes go through a pull request.

## License

[MIT](LICENSE) © Localy contributors.

## Target Hardware

Optimized for constrained devices first (not high-end GPUs): 16 GB RAM, Intel i5, no discrete GPU → 7B models at Q4_K_M. The honest baseline, not the best-case demo machine.
