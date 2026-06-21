# Project: [Your name here] — Fast, Accessible Local LLM Platform

> Paste this entire document to your coding agent (Claude Code, Cursor, etc.) as the project brief. It contains the vision, the constraints, what already exists, and the build order. Read it fully before writing code — the phase order is deliberate and load-bearing.

---

## 1. Vision

Make running open-source LLMs locally **fast and effortless** for anyone — starting on a single ordinary laptop with no dedicated GPU, scaling later to pooling multiple of the owner's own devices (PC, Android phone, another laptop), and eventually (lowest priority, separate effort) to opt-in pooling with other people over the internet.

The product is **not a new inference engine**. It is an intelligent layer on top of proven open-source inference engines (llama.cpp primarily) that:
1. Auto-detects the host machine's real capabilities and configures inference optimally — no manual tuning required.
2. Wraps this in a clean desktop app (Electron, or a comparably fast cross-platform shell — agent's call, justify the choice) so non-technical people can use it.
3. Later, lets a user's own devices pool memory/compute to run models too large for any single device.
4. Even later, extends pooling to consenting friends over the internet — gated behind solving trust, privacy, and abuse problems properly, not bolted on.

**Build order is sequential, not parallel.** Each phase must work solidly before the next begins. Do not scaffold all four phases shallowly at once — that produces something that demos badly and works nowhere.

**Build strategy, stated plainly:** Every piece of hard inference engineering already exists as mature open source and must be used as-is, not rewritten. llama.cpp does quantized inference. exo and Petals do distributed sharding. Ollama proves the UX pattern. None of this project's value comes from re-deriving that work — all of it comes from optimizing, configuring, and orchestrating those existing tools around the vision in this document: automatic per-machine tuning, one seamless app from solo to pooled, honest hardware-fit guidance, and an easy trusted-friends pooling tier. When in doubt about whether to write something from scratch or call an existing library/tool, default to calling it. Build new code only at the orchestration layer — the glue, the auto-tuning logic, the UI, the discovery/pooling coordination — never at the inference-kernel layer.

---

## 2. What already exists (do not reinvent these — use directly, improve only the orchestration around them)

| Layer | Existing tool | Use it for |
|---|---|---|
| Core inference engine | **llama.cpp** (C++) | Actual model execution — quantized GGUF, GPU offload, CPU SIMD kernels. This is the engine inside Ollama, LM Studio, GPT4All. |
| Python bindings | **llama-cpp-python** | Easiest way to call llama.cpp from a backend without writing C++ |
| Model format | **GGUF** | Quantized weight format (Q4_K_M, Q5_K_M, Q8_0, etc.) — what you'll load |
| Reference for "just works" UX | **Ollama** | Study its model pull/cache/run flow and REST API design (`/api/generate`, `/api/chat`) — match this API shape so existing tools work against your backend with zero changes |
| Reference for multi-device pooling | **exo** (github.com/exo-explore/exo) and **Petals** | Ring-topology pipeline parallelism, auto-discovery, dynamic layer partitioning by device memory. Study before building Phase 3 — don't redesign this from scratch |
| Faster serving engine (if you outgrow llama.cpp) | **vLLM** | Continuous batching, PagedAttention — more relevant once serving multiple simultaneous users than for solo desktop use |

**Your job is the layer none of these fully solve together**: automatic per-machine optimization + a genuinely friendly desktop app + opt-in pooling, in one coherent product. That combination is the gap.

---

## 3. What is actually new here (read this before cutting any "nice to have")

This project does not out-perform llama.cpp's raw inference speed — that engine is already built by a large team over years and is the execution core here, unchanged. Be honest about that in any pitch or README.

What is genuinely not solved, together, by any single existing tool today:

1. **Live, per-machine auto-tuning.** Ollama ships generic defaults. LM Studio exposes manual sliders. Neither runs an actual timed benchmark on first launch and uses that real number to set thread count, batch size, and context size for the exact machine in front of it. This is Section 5, items 1, 3, and 4 below — do not cut the first-run benchmark as a "nice to have." It is the point, not a polish step.
2. **One app, honestly seamless from solo to pooled.** Ollama only does solo. exo and Petals only do pooled, and assume the user already knows they need pooling and has gone and found a separate tool for it. No existing product opens, tells you plainly "this model fits on your device" or "this one doesn't, pool to run it," and makes pooling one click away inside the same app. This is the actual product idea — Phases 1 through 3 must feel like one continuous app, not three separate tools glued together.
3. **An honest hardware-fit advisor.** Most current tools let a non-technical person download a model that will thrash their machine or fail silently, with no warning beforehand. Telling the user up front what will and won't work well on their device, computed live rather than from a static chart, is small to build but directly serves the "make everyone able to use this" goal and is currently absent everywhere.
4. **A friends-only pooling tier, distinct from stranger-network pooling.** Petals is built for strangers contributing to a shared public model. exo's multi-device demos assume devices the same person already owns. A middle tier — easily pool with a handful of people you actually know and trust, over the internet, without needing public-network-scale trust/incentive infrastructure — is a real, currently underbuilt gap. Phase 4 below scopes this distinctly from full stranger-network pooling for this reason; do not collapse the two into one undifferentiated "internet pooling" bucket later.

If you find yourself describing this project as "faster than llama.cpp" or "a new inference engine," stop — that claim is false and will not survive a benchmark. The honest pitch is: the right model, sized right for the machine, tuned automatically, usable solo or pooled with people you trust, with no terminal required.

---

## 4. Target hardware — the actual constraint to design around

Primary development and test machine (treat as the baseline "must run well" target, not an edge case):

- CPU: 12th Gen Intel Core i5-1235U (10 cores: 2P+8E, 1.30 GHz base)
- RAM: 16 GB total (15.7 GB usable)
- GPU: **Intel Iris Xe integrated graphics, 128MB dedicated** — no usable discrete GPU, no meaningful CUDA/ROCm path
- Storage: 477 GB, ~59 GB free
- OS: Windows

**Implication the agent must internalize**: this machine is CPU-inference-bound. There is no dedicated-GPU offload path available here (Intel Iris Xe can do limited OpenCL/Vulkan compute but it is not a substitute for a real discrete GPU for LLM inference — do not assume CUDA, do not assume large VRAM). Realistic capability ceiling on this machine alone:
- 7B models at Q4_K_M: usable, target this as the default "just works" tier
- 13B models at Q4: borderline, slow but functional
- Anything bigger (30B+, 70B+): will not run well solo — this is exactly the case Phase 3 (device pooling) exists to solve, not something Phase 1 can fix with software cleverness

Do not promise or attempt "any model, full speed, single box" on this hardware — it is not physically possible (memory bandwidth bound, not a missing-feature problem). The honest, sellable promise is: **best possible speed for what this machine can hold, and a real path to bigger models via pooling.**

---

## 5. Phase 1 — Speed engine (single machine, build this first)

Goal: make inference on the host machine as fast as it can possibly be, automatically, with zero manual configuration from the user.

Build:
1. **Hardware probe on first launch / startup**: detect total RAM, CPU core count and type (P-cores vs E-cores if available), AVX2/AVX512 support, presence of any usable GPU backend (CUDA/Metal/ROCm/Vulkan — gracefully report "CPU only" when, as on the dev machine, none apply), free disk space.
2. **Auto quant/model-fit advisor**: given detected RAM, recommend which quantization level fits comfortably with headroom for OS + context, and warn before letting the user pick something that will spill to swap or fail to load.
3. **llama.cpp wrapper (via llama-cpp-python or direct bindings)** as the execution core. Auto-set: thread count (favor P-cores), batch size, context size defaults, mmap usage. Expose advanced overrides for power users but never require them.
4. **Benchmark-on-first-run**: run a short timed inference to measure actual tokens/sec on this exact machine, store it, use it to set expectations in the UI ("on this device, expect ~X tok/s on 7B models") rather than guessing.
5. **Speculative decoding support** where a compatible small "draft" model is available for the chosen main model — real, measurable speedup on CPU, not just GPU.
6. Stretch: **continuous batching** support, useful once this becomes a household-shared backend (Phase 3) serving more than one requester at a time.

Definition of done for Phase 1: on the dev machine, a 7B Q4 model loads, the app reports an accurate expected tok/s before generating, and actual throughput matches or beats a default/untuned Ollama install on the same machine and same model.

---

## 6. Phase 2 — App layer (desktop app, build second)

Goal: make Phase 1 usable by someone who has never opened a terminal.

Build:
1. **One-click installer** per OS, no terminal interaction required for basic use.
2. **Model catalog with honest hardware-fit labeling** — e.g. "Llama 3 8B — fits well on your device" vs "Mixtral 8x7B — will not fit, needs device pooling" computed from the Phase 1 hardware probe, not hardcoded.
3. **OpenAI-compatible REST API** (`/v1/chat/completions` shape) exposed locally, so the user's existing tools (IDE extensions, chat UIs, agent frameworks) work against this backend immediately. This is a hard requirement, not optional — it's what makes the project usable beyond its own UI on day one.
4. **Simple chat UI**: model picker, streaming responses, basic settings (context length, temperature) — clean, not feature-bloated.
5. Electron is a reasonable default for this (mature, cross-platform, huge ecosystem) — but the agent should evaluate Tauri as an alternative if startup time/memory footprint matters more than ecosystem maturity for this project, and state the tradeoff explicitly before committing, since Electron's RAM overhead is non-trivial on a 16GB target machine.

Definition of done for Phase 2: a non-technical user can install, pick a model the app says will fit, and chat — without ever seeing a terminal.

---

## 7. Phase 3 — Pool your own devices (build third, after 1+2 are solid)

Goal: let the owner's own devices (this laptop + another laptop/PC + an Android phone) on the same network combine memory to run models too large for any one device alone.

Scope explicitly: **owner's own trusted devices on a local network first.** Do not jump to internet-wide pooling here — that's Phase 4.

Build:
1. **Auto-discovery** of the user's other devices on the same LAN (mDNS/Bonjour-style, zero manual IP entry) — study exo's approach.
2. **Pipeline-parallel layer sharding**: split model layers across available devices in a ring, weighted by each device's available memory (a stronger PC gets more layers than the phone). Start here, not tensor parallelism — pipeline parallelism tolerates normal Wi-Fi/ethernet latency far better and is simpler to get correct.
3. **Android support**: investigate llama.cpp's existing Android/Termux build path or an MLC-LLM Android runtime as the worker on phone — do not write a custom mobile inference engine from scratch.
4. **Graceful single-device fallback**: pooling must be fully optional. The app must work exactly as well solo (Phase 1+2 behavior) when no other devices are present or reachable — pooling is additive, never required.
5. Be explicit to the user about the tradeoff: pooling unlocks bigger models but adds network latency per layer-boundary hop; for a model that already fits on one device, solo is faster, not slower. The app should default to solo and only suggest pooling when the requested model doesn't fit locally.

Definition of done for Phase 3: a model too large for the laptop alone (e.g. a 13B+ that doesn't comfortably fit in 16GB) loads and runs by combining the laptop + at least one other LAN device, with the app correctly explaining why it's using pooled mode.

---

## 8. Phase 4 — Opt-in internet pooling with others (future, separate effort, scope only — do not build yet)

This phase is documented so the architecture from Phases 1-3 doesn't have to be reworked later, but it should **not** be implemented until 1-3 are solid and in real use. It is a meaningfully harder, different category of problem (distributed systems + security + trust), not a natural extension of a weekend's work.

**Split this into two distinct tiers — do not treat "internet pooling" as one undifferentiated bucket:**

**4a. Friends-only pooling (the more realistic, more differentiated target).** Pool with a small number of specific people the user already knows and trusts — invited by a code/link, not discovered. This sidesteps several of the hardest problems below: incentives are solved by the existing relationship, abuse risk is far lower in a known-small-group, and reputation systems aren't needed. This tier is genuinely underserved by existing tools (see Section 3, point 4) and is the more buildable, more valuable near-term target if Phase 4 is ever picked up.

**4b. Open/stranger-network pooling (Petals-style).** Pool with unknown participants on a public network. Treat this as a distant, possibly-never target. It requires solving all of the problems below at public-network scale, not small-trusted-group scale.

Known hard problems to solve before building either tier, not during:
- **Privacy**: prompts/activations transiting a friend's or stranger's machine. Needs a clear, honest answer for users before this ships, not an afterthought. Materially easier in 4a (known people) than 4b (strangers).
- **NAT traversal / connectivity**: most home devices aren't directly reachable from the internet; this needs relay/hole-punching infrastructure (e.g. patterns from WebRTC, libp2p) which is its own subsystem. Needed for both tiers.
- **Node churn**: peers joining/leaving mid-session (Petals' core challenge) — the scheduler must handle a node dropping without corrupting in-flight generation. Needed for both tiers, but smaller blast radius in 4a.
- **Abuse/integrity**: a malicious peer could return corrupted activations; needs verification or reputation, not blind trust. Largely a non-issue in 4a if invite-only; central problem in 4b.
- **Incentives**: why would someone leave their device pooling for you? Already answered in 4a (it's your friend). Unsolved and necessary in 4b.

If Phase 4 is ever picked up, start with 4a only. Do not attempt 4b until 4a has real users and the team has appetite for what is genuinely a separate, harder project.

When this phase is eventually scoped for real, treat it as effectively a new project that reuses the Phase 3 pipeline-parallel core, not a checkbox on top of it.

---

## 9. Non-negotiable constraints across all phases

- Never claim or design toward "any model at full speed on any hardware" — be honest in-product about what a given device can and can't run well, computed from the real-time hardware probe, not a static table.
- Solo (Phase 1+2) must always work with zero dependency on other phases. Pooling is opt-in and additive.
- Match Ollama's REST API shape where reasonable so the ecosystem of existing tools works against this backend immediately.
- Don't reimplement llama.cpp's kernels. Wrap and configure it; that's the leverage point.
- Optimize first for the constrained dev machine (16GB RAM, no discrete GPU) as the realistic baseline user — not for a hypothetical RTX 4090 owner.

---

## 10. First task for the agent

Start with Phase 1 only. Specifically:
1. Set up the hardware probe and print a clear capability report for the current machine.
2. Stand up a minimal llama-cpp-python backend that loads a 7B Q4_K_M GGUF model with auto-tuned thread/batch settings based on the probe.
3. Run the first-launch benchmark and report actual tok/s.
4. Compare that number against a default `ollama run` of the same model on the same machine, and report the delta.

Do not start Phase 2, 3, or 4 code until Phase 1's definition of done (Section 5) is met and confirmed.
