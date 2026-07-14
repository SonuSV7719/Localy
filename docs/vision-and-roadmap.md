# Localy — Vision & Roadmap

> Companion to [LOCALLM_PROJECT_SPEC.md](../LOCALLM_PROJECT_SPEC.md). The spec defines the phases; this document expands the *pooling* vision (share LLMs across a friend group), states the honest engineering truths that shape it, and lists the differentiating features — including ones not in the original spec. Read the spec first; this refines it, it does not replace it.

---

## 1. The vision in one line

**Any ordinary laptop should be able to run local LLMs — fast and auto-optimized when a model fits, and by pooling with nearby or trusted friends when it doesn't.**

Three ways people run models, one continuous app:

1. **Solo** — your laptop alone, auto-tuned. (Phase 1 ✅ / Phase 2 UI)
2. **Pooled nearby** — you + friends on the same WiFi or a shared hotspot combine RAM to run models no single device could hold. (Phase 3)
3. **Pooled over internet** — the same, with trusted friends who are far away. (Phase 4a)

---

## 2. The one honest truth (this shapes every design decision)

**Pooling makes big models *possible*, not *faster*.** This is physics, not a missing feature.

- A model that **fits on one laptop** is always **fastest solo** — zero network hops.
- Pooling exists for models that **fit on no single device** (e.g. 70B). Without it: won't run at all. With it: runs at a *usable* speed.
- Therefore the app **defaults to solo** and only suggests pooling when a model does not fit locally (spec §7.5, §9).

The honest, sellable promise:

> **"Run models your laptop alone could never load — by borrowing your friends' RAM. And claw back the speed with smart tricks."**

Never claim "pooling makes your 7B faster." It doesn't, and a benchmark will expose it.

### Why latency, not bandwidth, is the constraint

During generation the data passed between nodes per token is tiny (~16 KB — one hidden-state vector), so **bandwidth is rarely the bottleneck; round-trip latency per layer-boundary hop is.**

| Network | Typical per-hop latency | Verdict |
|---|---|---|
| Same WiFi / router | ~1–5 ms | Fine — pooling feels responsive |
| Hotspot (nearby) | ~1–5 ms | Fine — same as LAN |
| Internet (friends far) | ~30–100 ms | Hard — this is what makes Phase 4 a separate, harder project |

This is why **LAN + hotspot pooling (Phase 3) delivers ~80% of the "run it with friends" magic without the internet hard problems.**

---

## 3. Connection scenarios → phases

| Scenario | What it is | Phase | Difficulty | Core challenge |
|---|---|---|---|---|
| Same WiFi / router | Friends on one local network | 3 | Medium | mDNS discovery, layer sharding |
| Hotspot (no router) | One laptop becomes the network, others join | 3 | Medium | Same engineering as LAN — big UX win |
| Over internet | Trusted friends, far apart | 4a | Hard | NAT traversal, encryption, latency, node churn |
| Stranger network | Unknown public participants | 4b | Very hard / maybe never | Trust, abuse, incentives at scale |

Same-WiFi and hotspot are the **same code path** (local network). Internet is a genuinely separate subsystem.

---

## 4. Features

### 4.1 Already in the spec (Phases 3–4)
- Auto-discovery of the user's / friends' devices on the LAN (mDNS).
- Pipeline-parallel layer sharding, weighted by device memory.
- Android worker support (via llama.cpp Android build or MLC-LLM — not a custom engine).
- Graceful single-device fallback (pooling is always optional, never required).
- Friends-only invite tier (4a) kept distinct from stranger-network (4b).

### 4.2 New features added by this document (the real differentiators)

1. **QR / link instant-join** — host shows a QR code; friends on the same WiFi/hotspot scan it and the cluster forms in seconds. No IP addresses, no config. Serves the "effortless" mandate.
2. **Hotspot cluster mode** — turn one laptop into the network so friends sitting nearby can pool with no router at all.
3. **Pooled speculative decoding** — a small *draft* model runs fast on the local machine; the big pooled model only *verifies* proposed tokens. Directly recovers speed lost to network hops. An underexplored, genuine edge.
4. **Activation compression** — quantize the small inter-node tensors to int8 for transport. Cheap latency/bandwidth win, especially over the internet.
5. **Compute-aware sharding** — assign layers by *measured tok/s* (extending the Phase-1 benchmark), not just RAM, so a fast PC gets more layers than a phone even at equal RAM.
6. **Live "pool fit" advisor** — "Alone: up to 7B. With Sara + Alex online: up to 70B." Computed live. Turns the Phase-1 honesty engine into a social feature.
7. **Node-churn healing** — a friend closes their laptop mid-answer; the ring re-plans and continues instead of crashing. Tractable in the *small trusted group* case; a hard problem at public scale.
8. **Battery / contribution awareness** — a phone contributes only while charging; a laptop backs off on battery. Makes people willing to leave the app open.
9. **Privacy modes** — because prompts cross friends' machines: *trusted-plaintext* (default among friends) vs. *split-so-no-single-node-sees-the-whole-prompt* (for internet). Must be answered before Phase 4 ships, not bolted on.
10. **Partial model download** — each device pulls only *its* shard of layers, not the whole multi-GB file. Faster joins, less disk.

---

## 5. Honest build sequencing

The pooling scenarios are the soul of the product, but they need a home. Sequencing (spec §1 — build order is load-bearing):

```
Phase 1  Speed engine (solo, auto-tuned)                 ✅ done
Phase 2  Desktop app (Tauri chat UI + model catalog)     🟡 backend API done; UI is scaffold only
Phase 3  LAN + hotspot pooling  ← delivers most of the   ⬜ next after Phase 2
         "run it with friends nearby" vision
Phase 4a Friends-over-internet pooling                   ⬜ separate, harder project
Phase 4b Stranger-network pooling                        ⬜ distant / maybe never
```

**Why Phase 2 before Phase 3:** pooling needs a UI to show discovery, invites (QR), the "who's in the pool" view, and the live pool-fit advisor. You cannot demo or use pooling from a terminal. Finish the desktop app, then pooling has somewhere to live.

**Current concrete state:**
- Phase 1 core engine: complete.
- Phase 2 **API-server half**: complete (`backend/src/localy/api/` — OpenAI `/v1`, Ollama `/api`, system routes).
- Phase 2 **desktop shell half**: default Tauri + React + TS scaffold only (`desktop/`) — no Localy UI yet.

---

## 6. Non-negotiables carried from the spec

- Never claim "any model at full speed on any hardware." Be honest in-product, computed live.
- Solo always works with zero dependency on pooling. Pooling is additive and opt-in.
- Default to solo; suggest pooling only when the requested model doesn't fit locally.
- Don't reimplement llama.cpp kernels — wrap and orchestrate.
- Optimize first for the constrained baseline (16 GB RAM, no discrete GPU), not a high-end GPU box.
