# Localy Architecture

Localy is a highly optimized, developer-friendly local LLM serving platform. Rather than rebuilding raw inference kernels, Localy functions as an intelligent orchestration layer on top of `llama.cpp` (via `llama-cpp-python`). It auto-detects host hardware topology, dynamically tunes performance settings, assesses model fit, and exposes standard APIs for third-party tools.

---

## System Overview

```mermaid
graph TD
    subgraph Client Layer
        CLI[localy CLI]
        GUI[Tauri Desktop App]
        External[Third-party Clients e.g. Continue, LibreChat]
    end

    subgraph API Gateway
        FastAPI[FastAPI Server]
        RouterOpenAI[OpenAI Route /v1/*]
        RouterOllama[Ollama Route /api/*]
        RouterSystem[System /health, /ready, /system/*]
    end

    subgraph Core Engine
        ServiceModel[Model Service]
        ServiceHW[Hardware Service]
        Engine[Inference Engine]
        Llama[llama-cpp-python]
    end

    subgraph System Detection & Tuning
        Probe[Hardware Probe]
        Optimizer[Auto-Tuning Optimizer]
        Advisor[Model-Fit Advisor]
    end

    subgraph Storage & Cache
        Registry[Model Registry]
        StoreModel[GGUF Model Store]
        StoreConfig[Config Store]
        CacheTuning[Tuning Cache]
    end

    CLI --> FastAPI
    GUI --> FastAPI
    External --> FastAPI

    FastAPI --> RouterOpenAI
    FastAPI --> RouterOllama
    FastAPI --> RouterSystem

    RouterOpenAI --> ServiceModel
    RouterOllama --> ServiceModel
    RouterSystem --> ServiceHW

    ServiceModel --> Engine
    ServiceModel --> StoreModel
    StoreModel --> Registry

    ServiceHW --> Probe
    Probe --> Optimizer
    Probe --> Advisor
    Optimizer --> CacheTuning
    
    Engine --> Llama
    Engine --> Optimizer
```

---

## 1. Phase 1: Speed Engine Core

The Core Engine is built in Python (3.12+) and is organized as follows:

### Hardware Detection (`localy.hardware`)
To optimize CPU-bound local inference, the hardware probe detects fine-grained resource constraints rather than generic attributes:
- **CPU Topology (`cpu_topology.py`)**: Uses Windows API calls (`GetLogicalProcessorInformationEx` via `ctypes`) to identify physical vs. logical cores and distinguishes **P-cores (Performance)** from **E-cores (Efficient)**. On non-hybrid architectures, it falls back to standard thread/core maps.
- **SIMD Capability (`instruction_sets.py`)**: Checks instruction sets (AVX2, AVX-512, SSE4.2, ARM NEON) using CPU registers to decide compilation and engine-side feature flags.
- **GPU Backends (`gpu_detector.py`)**: Discovers GPU platforms (CUDA, ROCm, Metal, Vulkan, OpenCL) and parses VRAM capacity. On systems with integrated graphics (e.g. Intel Iris Xe), it reports capabilities but marks them as `usable_for_inference=False` to prevent massive memory thrashing.
- **Memory & Storage (`memory.py`, `storage.py`)**: Inspects physical/available RAM and estimates storage read speed to recommend if memory-mapped files (`mmap`) are safe to use.

### Auto-Tuning Engine (`localy.tuning`)
The auto-tuning engine bridges the gap between hardware detection and inference parameters:
- **Optimizer (`optimizer.py`)**: Automatically computes thread bounds. It maps `n_threads` to the physical P-core count to prevent E-cores from bottlenecks, and sets `n_threads_batch` to physical core counts for parallel prompt processing.
- **Model-Fit Advisor (`advisor.py`)**: Approximates the final memory envelope of a model before downloading. It calculates:
  $$\text{Memory Needed} = \text{Model Weight Size} + \text{KV Cache Buffer} + \text{OS Overhead}$$
  If the model envelope fits within the `safe_model_budget_bytes`, it returns `fits_well`. If it exceeds but falls within swap limits, it flags `fits_tight`. Otherwise, it marks the model as `does_not_fit` and suggests smaller quantization profiles.
- **First-Run Benchmark (`benchmark.py`)**: Executes standard warming and evaluation passes on first launch, collecting generation tokens/sec to build realistic user-facing performance predictions.

---

## 2. Phase 2: App & Server Gateway (implemented)

Localy packages the core engine into a lightweight desktop application:

### API Server (`localy.main`, `localy.api`)
Exposes a FastAPI web server running locally (`127.0.0.1` binding only for security).
- **OpenAI Compatibility**: Routes `/v1/chat/completions` to standard OpenAI chat payloads, formatting streaming outputs as standard Server-Sent Events (SSE).
- **Ollama Compatibility**: Implements `/api/chat` and `/api/generate` to support NDJSON stream formats, enabling drop-in compatibility with frontend extensions (e.g. Continue, Llama Coder).
- **Model Lifecycle**: Maintains a single model instance in memory at any time to preserve memory on low-RAM systems. Subsequent model requests automatically unload the active model and load the requested one.

### Desktop Shell (Tauri v2)
Uses **Tauri v2** over Electron for the desktop wrapper.
- **Resource Efficiency**: Tauri consumes $\sim 40\text{--}80\text{ MB}$ of RAM compared to Electron's $150\text{--}400\text{ MB}$. This saving is allocated directly to the model's context window budget.
- **Sidecar Architecture**: Spawns the python backend as a background sidecar process, tracking its lifespan, intercepting console outputs, and handling port binds.

---

## 3. Phase 3: LAN Device Pooling (implemented)

When a model exceeds local memory, Localy scales horizontally by **orchestrating
llama.cpp's RPC backend** (not a custom inference kernel):

- **Coordinator/Worker (`localy.pooling.coordinator`, `localy.pooling.worker`)**:
  A worker runs `ggml-rpc-server` (needs no model file). The coordinator runs
  `llama-server --rpc host:port,… --tensor-split …`, holds the GGUF, and streams
  each device's layers to it. Localy proxies its normal chat routes to the
  coordinator, so a pooled model is served through the same API as solo.
- **Auto-Discovery (`localy.pooling.discovery`)**: mDNS (`zeroconf`,
  `_localy._tcp`) so workers on the same WiFi/hotspot appear automatically; the
  Android worker advertises the same way.
- **Shard planning (`localy.pooling.shard_planner`)**: compute-aware
  water-filling — layers weighted by each device's speed, **capped by its RAM**,
  across any number of devices. Workers use `--cache` so weights aren't
  re-streamed on reconnect.
- **Security**: the RPC backend is insecure/LAN-only by design — used only on a
  trusted local network; internet exposure is Phase 4 (encrypted tunnel).

## 3b. API Access, Dynamic Catalog & Downloads (implemented)

- **API access (`localy.core.api_keys`, `localy.network.tunnel`)**: OpenAI/Ollama
  APIs are key-gated for remote callers; the app can expose them on the LAN or
  over a **Cloudflare quick tunnel**. See the Security Model below.
- **Dynamic catalog (`localy.inference.hf_catalog`)**: quantization variants are
  fetched live from Hugging Face (cached, offline fallback); users can search HF
  and add any GGUF model.
- **Background downloads (`localy.services.download_manager`, `localy.utils.download`)**:
  parallel, atomic (`.part`→rename), and resumable; run server-side so they
  survive UI navigation.

---

## 4. Phase 4: Internet-Wide Pooling (Scope)

Designed for future scale, Phase 4 separates remote pooling into two tiers:
- **Friends-Only Pooling (4a)**: Relies on WebRTC/libp2p for NAT traversal. Nodes are authenticated via private invite links. Since participants are known, security/abuse verification overhead is minimized.
- **Stranger Network Pooling (4b)**: A public-network tier requiring zero-trust validation of activation calculations, distributed ledger incentives, and complex peer reputation tracking. Treated as a separate future subsystem.

---

## Security Model

1. **Key-gated access**: The server binds `0.0.0.0` so LAN/tunnel clients can
   reach it, but non-loopback requests require a valid API key (fail-closed).
   Loopback (the app itself) is exempt; proxied requests always require a key so
   a tunnel can't bypass auth; management endpoints are loopback-only.
2. **Local Processing**: Model weights, prompts, and generation buffers stay on
   the user's own filesystem/RAM (or, in pooled mode, across the user's trusted
   LAN devices).
3. **RPC is LAN-only**: `ggml-rpc-server` is insecure by design and is only used
   on a trusted local network — never exposed directly to the internet.
4. **Integrity**: `.gguf` downloads are atomic (`.part`→rename) and verified via
   SHA-256 when a hash is available.
