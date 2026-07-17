# Changelog

All notable changes to Localy are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Rich chat experience: Markdown rendering, collapsible reasoning/thinking sections, stop-generation control, and delete/archive/rename for conversations, with quota-safe history handling.
- Real per-device pool contribution analysis, so each machine's share of a pooled run is measured rather than estimated.
- Opt-in autostart and a system-tray daemon mode for running Localy in the background.
- A new application icon.

### Fixed

- Connection-resilience improvements for more reliable streaming and pooled sessions across flaky networks.
- "Run pooled" now gives clear, staged feedback (elapsed time + status) instead of appearing to do nothing, and no longer aborts early: the client request timeout is disabled for the long model-load operation (previously it timed out after 12s while the backend kept loading). Errors are surfaced with actionable messages, and a success banner points users to the Chat tab.

## [0.1.0]

### Added

- Auto-tuned single-machine inference that adapts to available hardware.
- Desktop app with streaming chat, a browsable model catalog, and a one-click Windows installer.
- Device pooling over LAN or hotspot to combine multiple machines for a single model.
- OpenAI- and Ollama-compatible API with API keys and optional Cloudflare tunnel for remote access.

[Unreleased]: https://github.com/SonuSV7719/Localy/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/SonuSV7719/Localy/releases/tag/v0.1.0
