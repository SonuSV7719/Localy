# Localy Desktop (Phase 2)

Tauri v2 + React + TypeScript desktop app for Localy. Provides the onboarding
wizard (hardware scan → recommended model → first-run benchmark), a streaming
chat playground, and a model catalog with **live hardware-fit labels**.

The UI talks to the Localy backend REST API on `http://127.0.0.1:11434`
(OpenAI + Ollama compatible).

## Run it (dev mode — no Rust/installer needed)

Two terminals:

**1. Backend API** (from `../backend`):
```bash
cd ../backend
uv run localy serve            # serves on 127.0.0.1:11434
```

**2. Frontend UI** (from this `desktop/` folder):
```bash
npm install                    # first time only
npm run dev                    # Vite dev server on http://localhost:1420
```

Then open **http://localhost:1420** in a browser. The app auto-detects the
backend ("Backend Online" in the sidebar) and CORS is preconfigured for any
localhost port.

## Run as a native desktop window (Tauri)

```bash
npm run tauri dev
```

This opens the app in a native window. In dev mode it does **not** bundle the
Python backend — keep `uv run localy serve` running in a separate terminal
(the sidecar spawn is intentionally non-fatal when the bundled binary is
absent). For a fully self-contained installer, the backend must first be
compiled to `src-tauri/binaries/localy-backend` (e.g. with PyInstaller) so
Tauri can ship it as a sidecar — that packaging step is not yet wired up.

## What to test

1. **Onboarding** — "Start Hardware Scan" shows your real CPU/RAM/GPU profile.
2. **Model Catalog** — 8 models with live fit badges (7B → "Fits Well",
   14B → "Tight Fit" with recommendations). Download a small one
   (SmolLM2, ~1 GB) to try chat.
3. **Chat** — pick a downloaded model, send a message, watch it stream with a
   live tok/s readout.

## Structure

```
src/
  api/         client.ts (fetch + SSE/NDJSON streaming), endpoints.ts, types.ts
  pages/       SetupPage, ChatPage, ModelsPage
  App.tsx      shell: sidebar nav + health polling
src-tauri/     Rust shell; src/sidecar.rs spawns/kills the backend process
```
