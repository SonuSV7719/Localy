# Localy Backend

The Localy core engine and API server — auto-tuned local LLM inference on top of
`llama.cpp` (via `llama-cpp-python`).

## Install

```bash
uv sync
```

## Usage

```bash
uv run localy probe            # Detect hardware
uv run localy models           # List models with fit assessment
uv run localy pull <model>     # Download a model
uv run localy run <model>      # Interactive chat
uv run localy benchmark <model># Measure tokens/sec
uv run localy serve            # Start REST API (OpenAI + Ollama compatible) on :11434
```

See the [top-level README](../README.md) and [docs/](../docs) for architecture and API reference.
