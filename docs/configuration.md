# Configuration

Localy runs with sensible defaults and needs no configuration for normal use. This page documents what you *can* change — mostly relevant when running the backend from source, integrating over the API, or using device pooling.

All settings can be provided as **environment variables** prefixed with `LOCALY_`. For example, `LOCALY_PORT=8080` overrides the server port.

---

## Common settings

| Environment variable | Default | Description |
|---|---|---|
| `LOCALY_HOST` | `127.0.0.1` | Server bind address. `127.0.0.1` = localhost only (secure). The desktop app binds `0.0.0.0` so LAN/tunnel clients can reach it (gated by API key). |
| `LOCALY_PORT` | `11434` | API server port. Matches Ollama for drop-in compatibility. |
| `LOCALY_DATA_DIR` | *(OS user data dir)* | Root directory for all Localy data (models, config, keys). |
| `LOCALY_MODEL_DIR` | `{data_dir}/models` | Where downloaded GGUF models are stored. |
| `LOCALY_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `LOCALY_LOG_FORMAT` | `console` | `console` for development, `json` for production. |

## Inference defaults

| Environment variable | Default | Description |
|---|---|---|
| `LOCALY_DEFAULT_CONTEXT_LENGTH` | `4096` | Default context window (tokens), 512–131072. |
| `LOCALY_DEFAULT_TEMPERATURE` | `0.7` | Default sampling temperature, 0.0–2.0. |
| `LOCALY_DEFAULT_TOP_P` | `0.9` | Default nucleus sampling probability, 0.0–1.0. |

## Auto-tuning

Localy tunes these from your hardware automatically. Override only if you know what you're doing.

| Environment variable | Default | Description |
|---|---|---|
| `LOCALY_TUNING_PROFILE` | `balanced` | `conservative`, `balanced`, or `aggressive`. |
| `LOCALY_THREAD_COUNT_OVERRIDE` | *(auto)* | Force a thread count instead of auto-detecting. |
| `LOCALY_BATCH_SIZE_OVERRIDE` | *(auto)* | Force a batch size. |
| `LOCALY_USE_MMAP` | `true` | Memory-mapped model loading (recommended). |

## Device pooling

| Environment variable | Default | Description |
|---|---|---|
| `LOCALY_POOL_ENABLED` | `false` | Enable pooling features. Solo mode always works regardless. |
| `LOCALY_RPC_PORT` | `50052` | Port this device's RPC worker listens on when sharing. |
| `LOCALY_RPC_BIND_HOST` | `0.0.0.0` | Bind address for the RPC worker (`0.0.0.0` accepts LAN peers). |
| `LOCALY_COORDINATOR_PORT` | `8080` | Port for the local coordinator that pooled mode proxies to. |
| `LOCALY_LLAMA_BIN_DIR` | *(auto)* | Directory with the RPC-enabled `rpc-server` / `llama-server` binaries. Defaults to the bundled/vendored path if present. |

See [Device Pooling](device-pooling.md) for how these are used.

## Security

| Environment variable | Default | Description |
|---|---|---|
| `LOCALY_API_KEY` | *(none)* | A static API key. Usually you generate keys from the app's **API Access** tab instead; loopback access needs no key. |
| `LOCALY_CORS_ORIGINS` | `localhost:*`, `127.0.0.1:*`, `tauri://localhost` | Allowed CORS origins. |

> **Access control:** loopback requests are always allowed; every LAN/tunnel/internet request must present a valid API key (fail-closed). Key-minting and tunnel controls are loopback-only. Full model in the [API Reference](api-reference.md#global-headers--security).

## Telemetry

| Environment variable | Default | Description |
|---|---|---|
| `LOCALY_TELEMETRY_ENABLED` | `false` | Anonymous telemetry. **Off by default**, opt-in only. |

---

## Storage locations

By default Localy stores everything under your OS user-data directory (overridable with `LOCALY_DATA_DIR`):

```
{data_dir}/
├── models/        # downloaded GGUF model files (LOCALY_MODEL_DIR)
├── config/        # settings and cached hardware report
└── keys/          # API keys
```

Chat history is stored by the **desktop app** locally (per-user app storage), separate from the backend data directory.

---

## Setting environment variables

**Windows (PowerShell), current session:**

```powershell
$env:LOCALY_PORT = "8080"
uv run localy serve
```

**Windows (persistent, current user):**

```powershell
setx LOCALY_PORT 8080
```

**macOS / Linux (bash):**

```bash
LOCALY_PORT=8080 uv run localy serve
```

> When using the **desktop app**, the bundled backend is launched for you; to change its configuration you'd set the variable at the OS/user level before launching the app.
