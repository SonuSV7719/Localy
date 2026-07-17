# Troubleshooting & FAQ

Fixes for common issues. If your problem isn't here, please [open an issue](https://github.com/SonuSV7719/Localy/issues).

---

## Backend / connection

### The status dot says "Connecting…" and never turns green

- Give it ~10–15 seconds after launch — the backend takes a moment to start.
- Check the API directly: `curl http://127.0.0.1:11434/health` should return `{"status":"ok"}`.
- Another process may be using port `11434`. Change it with `LOCALY_PORT` (see [Configuration](configuration.md)) or stop the conflicting process.
- Antivirus/firewall may have blocked the bundled backend executable — allow it and relaunch.

### The status dot briefly flips to "Connecting…" during a long response

This is normal. The backend is busy generating (it's single-threaded per request), so an occasional health check is slow. Localy only reports a real disconnect after **several consecutive** failed checks, and re-checks immediately when you refocus the window. No action needed.

### Chat says "connection lost" after a while / after switching tabs

Switching tabs inside the app does not stop the backend. If you enabled **Keep running when window is closed** in Settings, the backend also survives closing the window. If you did *not* enable it, closing the window stops the backend by design — reopen the app.

---

## Chat

### A long response disappeared

Fixed in current versions: chat history is written safely and, if local storage fills up, the **oldest** conversations are trimmed so the newest response is never lost. If you're on an old build, update. To free space yourself, delete or archive old conversations.

### The model's answer includes its "thinking" / `<think>` text

Reasoning models emit a chain of thought. Localy detects `<think>`/`<thinking>` and tucks it into a collapsible **Reasoning** panel, showing the final answer by default. If you see raw `<think>` text, update to a current version.

### Code blocks or Markdown look wrong

Localy renders Markdown (headings, lists, links, fenced code with a Copy button). If formatting looks off, it's usually the model's own output; try rephrasing the prompt or a different model.

---

## Models

### A model I want shows "does not fit"

Your hardware can't safely hold it at that quantization. Options: pick a **smaller quantization** (e.g. `Q4_K_M` instead of `Q8_0`), choose a **smaller model**, or **pool devices** (see [Device Pooling](device-pooling.md)).

### A download stalled or failed

Downloads are resumable — cancel and restart it; partial progress is kept. Check your disk space and network. Hugging Face rate limits or outages can also cause transient failures.

---

## Device pooling

### I joined a device but chat still uses only one machine

You must load a model across the pool: **Device Pool → select model → Run pooled**. Joining a device only makes it *available*; it isn't used until a model is loaded pooled. See [Device Pooling](device-pooling.md#does-joining-a-device-start-using-it-no--one-extra-step).

### Scan finds no devices

Every helper device must have **Share this device** turned on, and all devices must be on the **same WiFi or hotspot**. Firewalls can block the RPC port (`50052`). Then scan again.

### Pooled generation is slower than running solo

Expected when the model already fits on one device — pooling adds network hops between layers. Pool only for models too big to fit otherwise.

---

## API access

### External tools get 401 / access denied

LAN, tunnel, and internet requests require an API key (loopback doesn't). Generate one in **API Access**, and send it as `Authorization: Bearer <key>` or `X-API-Key: <key>`. If no keys exist, remote access is denied by design (fail-closed).

### I can't create a key or start the tunnel from another device

Key-minting and tunnel controls are **loopback-only** on purpose — do them from the app on the host machine, not remotely.

---

## FAQ

**Do I need Python to use the desktop app?**
No. The Windows installer bundles the backend. Python is only needed to run the backend from source.

**Does pooling make models faster?**
No — it makes *bigger* models possible. A model that fits on one device is faster solo.

**Where are my models and chats stored?**
Models and backend data live under your user-data directory (`LOCALY_DATA_DIR`); chat history is stored by the desktop app locally. See [Configuration → Storage](configuration.md#storage-locations).

**Is my data sent anywhere?**
Inference runs locally. Telemetry is off by default. The catalog fetches model metadata from Hugging Face, and the optional internet tunnel exposes your API only while you enable it.

**Can I use Localy with Continue / LibreChat / the OpenAI SDK?**
Yes — point them at `http://127.0.0.1:11434` (with a key for remote access). See the [API Reference](api-reference.md).

**How do I make Localy run in the background like a service?**
Enable **Keep running when window is closed** and **Start on login** in Settings. Stop it from the tray → "Stop backend & quit". See the [User Guide](user-guide.md#settings).
