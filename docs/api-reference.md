# Localy REST API Reference

Localy serves HTTP REST APIs locally at `http://127.0.0.1:11434` by default. It provides complete compatibility with both OpenAI and Ollama API payloads, letting existing tools (SDKs, IDE extensions, etc.) point directly to Localy with zero modification.

---

## Global Headers & Security

By default, Localy binds strictly to `127.0.0.1` and does not require an API key for local developer usage.
If configured with an API key, all calls must include the authorization header:

```http
Authorization: Bearer <your_api_key>
```

---

## 1. OpenAI-Compatible v1 Endpoints

### List Models
Retrieve all models registered and available locally.

* **URL**: `/v1/models`
* **Method**: `GET`
* **Response**:
```json
{
  "object": "list",
  "data": [
    {
      "id": "smollm2:2b",
      "object": "model",
      "created": 1718976000,
      "owned_by": "localy"
    }
  ]
}
```

### Chat Completions
Creates a model response for the given chat conversation. Supports standard JSON responses and Server-Sent Events (SSE) token streaming.

* **URL**: `/v1/chat/completions`
* **Method**: `POST`
* **Headers**: `Content-Type: application/json`
* **Payload**:
```json
{
  "model": "smollm2:2b",
  "messages": [
    {
      "role": "user",
      "content": "Tell me a joke."
    }
  ],
  "temperature": 0.7,
  "top_p": 0.9,
  "max_tokens": 1024,
  "stream": false
}
```
* **Response (Non-Streaming)**:
```json
{
  "id": "chatcmpl-mock",
  "object": "chat.completion",
  "created": 1718976005,
  "model": "smollm2:2b",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Why don't scientists trust atoms? Because they make up everything!"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 11,
    "total_tokens": 23
  }
}
```
* **Streaming Response (`stream: true`)**:
Exposes a `text/event-stream` returning data chunks as SSE events.
```http
data: {"id": "chatcmpl-mock", "object": "chat.completion.chunk", "created": 1718976005, "model": "smollm2:2b", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Why"}, "finish_reason": null}]}

data: {"id": "chatcmpl-mock", "object": "chat.completion.chunk", "created": 1718976005, "model": "smollm2:2b", "choices": [{"index": 0, "delta": {"content": " don't"}, "finish_reason": null}]}

...

data: {"id": "chatcmpl-mock", "object": "chat.completion.chunk", "created": 1718976005, "model": "smollm2:2b", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}

data: [DONE]
```

---

## 2. Ollama-Compatible Endpoints

### List Local Models (Tags)
Lists models currently downloaded and available to load.

* **URL**: `/api/tags`
* **Method**: `GET`
* **Response**:
```json
{
  "models": [
    {
      "name": "smollm2:q4_k_m",
      "model": "smollm2:q4_k_m",
      "modified_at": "2026-06-21T11:02:50.000Z",
      "size": 1073741824,
      "digest": "Q4_K_M",
      "details": {
        "parent_model": "",
        "format": "gguf",
        "family": "llama",
        "families": ["llama"],
        "parameter_size": "1.7B",
        "quantization_level": "Q4_K_M"
      }
    }
  ]
}
```

### Chat Completions
Ollama-compatible chat completion returning line-delimited JSON.

* **URL**: `/api/chat`
* **Method**: `POST`
* **Payload**:
```json
{
  "model": "smollm2:q4_k_m",
  "messages": [
    {
      "role": "user",
      "content": "Hello!"
    }
  ],
  "stream": false
}
```
* **Response**:
```json
{
  "model": "smollm2:q4_k_m",
  "created_at": "2026-06-21T11:03:00.000Z",
  "message": {
    "role": "assistant",
    "content": "Hi there! How can I help you today?"
  },
  "done": true,
  "total_duration": 450000000,
  "load_duration": 120000000,
  "prompt_eval_count": 8,
  "prompt_eval_duration": 30000000,
  "eval_count": 10,
  "eval_duration": 300000000
}
```

### Generate Completion
Runs a single-turn completion prompt.

* **URL**: `/api/generate`
* **Method**: `POST`
* **Payload**:
```json
{
  "model": "smollm2:q4_k_m",
  "prompt": "The sky is",
  "stream": false
}
```
* **Response**:
```json
{
  "model": "smollm2:q4_k_m",
  "created_at": "2026-06-21T11:03:05.000Z",
  "response": " blue because of Rayleigh scattering.",
  "done": true,
  "prompt_eval_count": 4,
  "eval_count": 8
}
```

### Pull Model (Download)
Downloads and verifies a model from the registry. Streams download progress back in JSON chunks.

* **URL**: `/api/pull`
* **Method**: `POST`
* **Payload**:
```json
{
  "name": "smollm2:2b",
  "stream": true
}
```
* **Streaming Response**:
```json
{"status": "downloading", "digest": "sha256:...", "total": 1073741824, "completed": 268435456}
{"status": "downloading", "digest": "sha256:...", "total": 1073741824, "completed": 536870912}
...
{"status": "success"}
```

---

## 3. System & Monitoring Endpoints

### Health Check (Liveness)
Check if the web server is online.

* **URL**: `/health`
* **Method**: `GET`
* **Response**:
```json
{
  "status": "ok"
}
```

### Readiness Check
Check if the hardware has been probed and see what model is currently loaded in memory.

* **URL**: `/ready`
* **Method**: `GET`
* **Response**:
```json
{
  "status": "ready",
  "model_loaded": true,
  "active_model": "smollm2:2b"
}
```

### Full Hardware Report
Runs a detailed hardware capabilities probe and returns CPU topology, GPU availability, RAM budgets, and SIMD support.

* **URL**: `/system/hardware`
* **Method**: `GET`
* **Response**:
```json
{
  "hardware_hash": "a5f8e12d...",
  "cpu": {
    "brand": "Intel Core i5-1235U",
    "architecture": "x86_64",
    "logical_cores": 12,
    "physical_cores": 10,
    "p_cores": 2,
    "e_cores": 8,
    "is_hybrid": true
  },
  "gpu": {
    "device_name": "Intel Iris Xe",
    "vram_total_mb": 128,
    "usable_for_inference": false,
    "backend": "CPU_ONLY"
  },
  "memory": {
    "total_bytes": 17179869184,
    "available_bytes": 12884901888,
    "safe_model_budget_bytes": 10737418240
  },
  "storage": {
    "path": "C:\\Users\\sonup\\AppData\\Local\\Localy\\models",
    "free_bytes": 63350767616,
    "read_speed_mbps": 500.0,
    "is_ssd": true
  },
  "instruction_sets": {
    "avx2": true,
    "best_available_simd": "AVX2"
  }
}
```

### Model Fit Assessment
Evaluates whether a model can load and run on the host's hardware boundaries without running out of RAM or spilling to swap space.

* **URL**: `/system/hardware/fit/{model_id}` (e.g. `/system/hardware/fit/smollm2:2b`)
* **Method**: `GET`
* **Parameters**:
  - `context`: (Optional query integer) target context size to evaluate.
* **Response**:
```json
{
  "model_id": "smollm2:2b",
  "fit_level": "fits_well",
  "required_memory_bytes": 1572864000,
  "safe_budget_bytes": 10737418240,
  "recommendations": [
    "Model weights (970.00 MB) fit comfortably within safe RAM budget (10.00 GB).",
    "Balanced thread profile selected: 2 threads (P-core match)."
  ]
}
```

### Run Benchmark
Triggers a standardized generation pass to benchmark local tokens/sec capabilities.

* **URL**: `/system/benchmark`
* **Method**: `POST`
* **Payload**:
```json
{
  "model": "smollm2:2b",
  "iterations": 3
}
```
* **Response**:
```json
{
  "model_id": "smollm2:2b",
  "prompt_tokens_per_second": 32.5,
  "generation_tokens_per_second": 12.2,
  "time_to_first_token_ms": 110.0,
  "iterations_run": 3,
  "hardware_hash": "a5f8e12d..."
}
```
