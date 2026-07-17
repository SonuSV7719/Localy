# Localy Documentation

Welcome to the Localy docs. Start here and jump to what you need.

## For users

| Guide | What it covers |
|---|---|
| [Installation](installation.md) | Install the desktop app, or build from source |
| [User Guide](user-guide.md) | Chat, model catalog, API access, and settings |
| [Device Pooling](device-pooling.md) | Combine multiple devices to run bigger models |
| [Configuration](configuration.md) | Ports, environment variables, storage, API keys |
| [Troubleshooting](troubleshooting.md) | Fixes for common issues + FAQ |

## For developers & integrators

| Guide | What it covers |
|---|---|
| [API Reference](api-reference.md) | OpenAI- and Ollama-compatible REST endpoints |
| [Architecture](architecture.md) | How the system is put together |
| [Development Guide](development-guide.md) | Dev environment, CLI, tests |
| [Vision & Roadmap](vision-and-roadmap.md) | Where Localy is heading and why |

## What is Localy, in one paragraph

Localy is a local LLM platform built on top of `llama.cpp`. It auto-detects your
hardware and tunes inference for it, tells you honestly whether a model will fit
before you download it, and lets you pool several devices to run models too big
for one machine. It runs as a desktop app (bundled backend, no Python required)
and as a CLI/REST server that speaks both the OpenAI and Ollama APIs.

New here? Read [Installation](installation.md) → [User Guide](user-guide.md).
