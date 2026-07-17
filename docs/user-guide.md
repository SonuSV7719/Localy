# User Guide

This guide walks through the Localy desktop app. If you haven't installed it yet, see [Installation](installation.md).

The app has five sections in the left sidebar:

- [💬 Chat Playground](#chat-playground)
- [📁 Model Catalog](#model-catalog)
- [🔗 Device Pool](#device-pool)
- [🔌 API Access](#api-access)
- [⚙️ Settings](#settings)

The status dot at the bottom of the sidebar shows backend health and your hardware summary.

---

## First launch

On first run, Localy performs a one-time **hardware probe** (CPU topology, RAM, GPU, SIMD support) and shows a short onboarding. This is what powers auto-tuning and fit advising. You can revisit your hardware summary any time from the sidebar footer.

---

## Model Catalog

This is where you download and manage models.

- **Fit badges** — every model/quantization shows *fits well*, *fits tight*, or *does not fit* for **your** hardware, computed before you download anything.
- **Quantization picker** — choose a variant (e.g. `Q4_K_M`); sizes are pulled live from Hugging Face.
- **Add any GGUF** — search Hugging Face and add any GGUF repo to your catalog.
- **Background downloads** — downloads are parallel, resumable, and atomic. They keep running while you switch tabs, with live speed/ETA, and can be cancelled (partial progress is kept for resume).
- **Delete** — remove a downloaded model to free disk space.

Pick a model that *fits well* for the best experience; *fits tight* will work but may be slow or memory-pressured.

---

## Chat Playground

Select a downloaded model from the **Active Model** dropdown (use the **⧉ copy** button next to it to copy the exact model id for API/CLI use), click **+ New Chat**, and start typing.

### What you get

- **Streaming responses** with a live tokens/second and token-count readout.
- **Markdown rendering** — headings, lists, links, and fenced **code blocks with a Copy button**.
- **Collapsible reasoning** — reasoning models (DeepSeek-R1 distills, Qwen, Phi, …) emit a chain of thought in `<think>` tags. Localy hides it behind a **Reasoning** toggle so you see the answer first; expand it if you want to read the model's thinking.
- **Stop** — interrupt a running generation at any time; tokens produced so far are kept.
- **Multi-device badge** — when a model is served across a pool, a **🔗 N devices** badge appears; click it to see each device's live contribution. See [Device Pooling](device-pooling.md).

### Managing conversations

Conversations are listed in the sidebar with **Active** and **Archived** tabs. Hover a conversation for actions:

| Action | Effect |
|---|---|
| ✎ Rename | Give the conversation a custom title |
| 🗄 Archive / ⇤ Unarchive | Move it out of / back into the Active list |
| 🗑 Delete | Remove it permanently (asks for confirmation if it has messages) |

> **Storage note:** chat history is stored locally in the app. Localy keeps your most recent conversations safe even if storage fills up — if the limit is reached, the oldest conversations are trimmed automatically so new responses are never lost.

---

## Device Pool

Combine several devices to run models too big for any one of them. In short:

1. On each helper device: **Device Pool → 🤝 Share this device**.
2. On your main device: **Scan** (or add `host:port`) → **Join**.
3. Pick a model → **Run pooled**.
4. Chat with it as usual.

The **Live Contribution** card shows which device holds which share of the model, flags idle devices, and tells you whether the split is efficient.

This has its own full guide, including the important detail that **joining a device does not start using it until you Run pooled**: **[Device Pooling](device-pooling.md)**.

---

## API Access

Localy exposes an OpenAI- and Ollama-compatible API so other apps (Continue, LibreChat, any OpenAI SDK) can use your local models.

From this tab you can:

- See your **local** and **LAN** URLs and the port.
- **Generate / revoke API keys.** The full key is shown once at creation — copy it then.
- Start/stop a **Cloudflare internet tunnel** to expose the API publicly.

**Security model:** loopback requests (same machine) never need a key; every LAN, tunnel, or internet request must present a valid key, and it's fail-closed (no keys = no remote access). Key-minting and tunnel controls are loopback-only. Full details in the [API Reference](api-reference.md#global-headers--security).

---

## Settings

- **Keep running when window is closed** — closing the window minimizes Localy to the system tray and keeps the local server online (so pooled devices and API clients stay connected). Click the tray icon to reopen.
- **Start Localy automatically on login** — launch Localy in the background when you sign in.

With both enabled, Localy behaves like a **daemon**: it starts on login and survives window closes. To fully stop it, use the tray icon → **"Stop backend & quit"**, or the **Stop backend & quit Localy** button in Settings.

---

## Tips

- A model that **fits well** on one device is faster run solo than pooled — pooling is for going *bigger*, not *faster*.
- Use the **⧉ copy model name** button in Chat to get the exact id for API calls.
- If the status dot flips to "Connecting…" briefly during a heavy generation, that's normal — Localy only reports a real disconnect after several consecutive failed checks.

Stuck? See [Troubleshooting](troubleshooting.md).
