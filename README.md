# Localy

**Fast, accessible local LLM platform with auto-tuned inference.**

Run open-source LLMs locally — auto-detected, auto-tuned, zero configuration required.

---

## What Makes Localy Different

| Problem | Ollama/LM Studio | Localy |
|---|---|---|
| Thread configuration | Generic defaults | Auto-tuned from your actual CPU (P-cores vs E-cores) |
| "Will this model fit?" | Download it and find out | Pre-download fit check with honest recommendations |
| Performance expectations | No prediction | First-run benchmark reports actual tok/s |
| Bigger models | Single device only | Pool your own devices (Phase 3) |

**Honest promise**: best possible speed for what your machine can hold, and a real path to bigger models via pooling.

**Not promised**: "any model at full speed on any hardware" — that's physically impossible.

---

## Quick Start

```bash
# Install
cd backend
pip install uv  # If you don't have uv
uv sync

# Detect your hardware
uv run localy probe

# See what models are available (with fit assessment)
uv run localy models

# Download a model (checks fit before downloading)
uv run localy pull llama3.1:8b

# Chat
uv run localy run llama3.1:8b

# Benchmark (compare against Ollama on same model)
uv run localy benchmark llama3.1:8b

# Start API server (OpenAI + Ollama compatible)
uv run localy serve
```

## CLI Commands

| Command | Description |
|---|---|
| `localy probe` | Detect and display hardware capabilities |
| `localy models` | List available models with fit assessment |
| `localy pull <model>` | Download a model from the registry |
| `localy fit <model>` | Detailed hardware fit check |
| `localy run <model>` | Interactive chat with auto-tuned inference |
| `localy benchmark <model>` | Performance benchmark (reports tok/s) |
| `localy serve` | Start REST API server |

## API Compatibility

Localy exposes both OpenAI and Ollama-compatible APIs:

```bash
# OpenAI-compatible
curl http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "llama3.1:8b", "messages": [{"role": "user", "content": "Hello"}]}'

# Ollama-compatible
curl http://localhost:11434/api/chat \
  -d '{"model": "llama3.1:8b", "messages": [{"role": "user", "content": "Hello"}]}'
```

## Architecture

```
User → CLI / Desktop App → FastAPI Server → llama-cpp-python → llama.cpp
         ↕                      ↕
    Hardware Probe ←→ Auto-Tuning Engine
```

Localy does **not** reimplement inference. It wraps llama.cpp and adds:
1. Live per-machine auto-tuning
2. Honest hardware-fit advising
3. Curated model registry (Ollama-style `pull` commands)
4. Device pooling for bigger models (Phase 3)

## Build Phases

- **Phase 1**: Speed engine — auto-tuned single-machine inference ✅
- **Phase 2**: Desktop app — Tauri app (chat, model catalog, one-click installer) ✅
- **Phase 3**: Device pooling — combine LAN/hotspot devices for bigger models ✅
- **Phase 4**: Internet pooling — friends-only, then open network (scope only)

## Features

- **Desktop app** (Tauri + React): onboarding, streaming chat with sessions, and a
  one-click Windows installer that bundles the backend (no Python needed).
- **Dynamic model catalog**: every quantization variant is pulled live from
  Hugging Face with real sizes; search and add any GGUF model.
- **Background downloads**: parallel, resumable, atomic — keep running across tab
  switches, with live speed/ETA and cancel.
- **Device pooling**: run models too large for one machine by splitting layers
  across any number of devices on the same WiFi/hotspot (llama.cpp RPC backend),
  weighted by each device's speed and memory. Includes a **zero-setup Android
  worker app** (install, tap Connect).
- **API access**: OpenAI-compatible API for other apps/people — generate API
  keys, expose on the LAN, or over the internet via a Cloudflare tunnel.

See [docs/vision-and-roadmap.md](docs/vision-and-roadmap.md) for the full pooling vision (share models across a friend group over WiFi/hotspot/internet), the honest "why pooling ≠ faster" reasoning, and the differentiating features.

## Target Hardware

Optimized for constrained devices first (not high-end GPUs):
- 16GB RAM, Intel i5, no discrete GPU → 7B models at Q4_K_M
- The honest baseline, not the best-case demo machine

## License

MIT
