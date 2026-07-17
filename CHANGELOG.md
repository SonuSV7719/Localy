# Changelog

All notable changes to Localy are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Vision (images) — backend foundation.** The API now accepts OpenAI-style multimodal message content (text + `image_url` parts); the engine loads a vision chat handler when a model ships an `mmproj` projector (Qwen2.5-VL, LLaVA, MiniCPM-V, Moondream, …), and text-only models safely flatten image parts to a placeholder. Models are flagged `supports_vision` so clients can gate an image button. (Image UI in the desktop/mobile chat and end-to-end verification with a real vision model are the next step.)
- **Attach images in desktop chat (vision models).** When the selected model supports vision (`supports_vision`), an image button appears; attached images are sent to the model as OpenAI `image_url` parts. Hidden for text-only models.
- **Attach documents in chat.** Attach PDFs, text, Markdown, code, JSON/CSV, etc.; Localy extracts the text (server-side, PDFs via pypdf) and feeds it to the model as context. Works with any text model — the chat bubble shows filename chips, and long files are truncated to fit the context. (Image/vision attachments for capable models are planned next.)
- Model Catalog search shows a loading spinner and its results dropdown now closes on outside-click / Esc.
- **Android chat sessions.** The phone chat now keeps multiple conversations in on-device **SQLite**, with a sessions drawer to switch chats and **rename / archive / delete** — all stored locally on the device. Plus **document attachments** on mobile (PDF/text/code) via the same extraction as desktop, and a branded launcher icon + splash screen.

- Rich chat experience: Markdown rendering, collapsible reasoning/thinking sections, stop-generation control, and delete/archive/rename for conversations, with quota-safe history handling.
- Real per-device pool contribution analysis, so each machine's share of a pooled run is measured rather than estimated.
- Opt-in autostart and a system-tray daemon mode for running Localy in the background.
- A new application icon.

### Fixed

- **Robustness audit fixes across backend, desktop, and Android:**
  - Backend: streaming inference now holds the engine lock so a concurrent model load/unload can't free the native context mid-stream (use-after-free); streaming worker tasks are retained (no GC-hang); `/system/extract` caps upload size (no OOM); pooled-proxy handles non-JSON upstream responses; API-key comparison is constant-time; mmproj matching prefers the projector whose name matches the model.
  - Desktop: model-fit badges are now truly per-quantization (were showing the same model-level result for every quant); a single oversized conversation is no longer wiped from storage; the "streaming" bubble only shows on the chat that's actually generating; delete/archive picks the next chat from the current tab; manual pool-join validates the port; image-only prompts no longer leak internal markers to the model.
  - Android: all SQLite access moved off the UI thread (no ANR on long chats); switching chats mid-stream can no longer corrupt or misfile the reply into the wrong session; mDNS server resolves are serialized so a second PC reliably appears.

- Connection-resilience improvements for more reliable streaming and pooled sessions across flaky networks.
- Model **fit assessment is now exact for weights**: it uses each variant's real Hugging Face file size instead of a parameter×quantization estimate. This fixes inaccurate badges for **search-and-added models** whose parameter count couldn't be parsed from the repo name (previously they could falsely show "fits well"). When neither a real size nor a parameter count is available, the badge is now cautionary rather than a false green. Covered by unit tests.
- "Run pooled" now gives clear, staged feedback (elapsed time + status) instead of appearing to do nothing, and no longer aborts early: the client request timeout is disabled for the long model-load operation (previously it timed out after 12s while the backend kept loading). Errors are surfaced with actionable messages, and a success banner points users to the Chat tab.
- Pooled model loading is now **non-blocking and tracked on the server**: the Device Pool page shows a live progress panel (percent, elapsed, ETA, data transferred to workers, worker count, latest log) that **survives tab switches and window close** — loading continues on the server and the panel resumes when you return. Chat only routes to the pool once the coordinator is actually ready.
- The Localy server now advertises itself on the LAN over mDNS (`_localy-api._tcp`) so client apps can auto-discover it.
- **Android app: a Chat screen.** From the phone you can now chat with a model served by your PC — including one pooled across the phone and other devices. Auto-discovers the PC on WiFi, remembers the server + API key, streams responses, and shows a full live pooled-load progress panel (percent, elapsed, ETA, data transferred, status).

## [0.1.0]

### Added

- Auto-tuned single-machine inference that adapts to available hardware.
- Desktop app with streaming chat, a browsable model catalog, and a one-click Windows installer.
- Device pooling over LAN or hotspot to combine multiple machines for a single model.
- OpenAI- and Ollama-compatible API with API keys and optional Cloudflare tunnel for remote access.

[Unreleased]: https://github.com/SonuSV7719/Localy/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/SonuSV7719/Localy/releases/tag/v0.1.0
