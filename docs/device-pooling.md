# Device Pooling

Device pooling lets you **combine multiple devices** — your own, or friends' on the same WiFi/hotspot — to run a model that's **too large for any single machine**. Localy splits the model's layers across the devices using the [llama.cpp RPC backend](https://github.com/ggerganov/llama.cpp/tree/master/tools/rpc), weighted by each device's memory and speed.

> **Read this first:** pooling unlocks **bigger** models, not **faster** ones. A model that already fits comfortably on one device will run *faster solo* than split across the network, because network latency is added between layers. Pool when a model won't otherwise fit. See [why pooling ≠ faster](vision-and-roadmap.md).

---

## Does joining a device start using it? No — one extra step

This is the most common point of confusion, so to be explicit:

**Joining a device only makes it _available_ in your pool. It is not used for inference until you load a model across the pool with "Run pooled".**

Under the hood: `join` registers the device in pool membership. Your chat only routes to the pool once a **coordinator** is running for that model — which happens when you click **Run pooled** (or call `POST /pool/load`). Until then, chat uses your local device as usual.

---

## Step by step

### 1. Share each helper device

On **every device you want to contribute** (not your main one):

- Open Localy → **Device Pool** → **🤝 Share this device**.
- This starts that device's RPC worker and advertises it on the local network.

A device that isn't sharing can't be joined. On Android, install the **Localy worker app** and tap Connect — it advertises the same way.

> All devices must be on the **same WiFi or hotspot**.

### 2. Join the devices into your pool

On your **main device** (the one you'll chat from):

- **Device Pool → 🔍 Scan WiFi/Hotspot** to auto-discover shared devices, then **Join** each (or **Join all**).
- Or add one manually by address: `host:port` (e.g. `192.168.1.5:50052`), then **Add**.

Joined devices appear under **Pool Status** with their approximate memory budget. The pooled memory total is shown at the top.

### 3. Load a model across the pool

Still on your main device, in **Run a Model Across the Pool**:

1. Select a model.
2. **Check fit** — Localy computes whether the model fits across the *combined* memory and shows the planned per-device layer split.
3. **Run pooled** — this spawns the coordinator and splits the model across the devices. `Run pooled` is enabled only when the model fits.

Once loaded, **Pool Status** shows **● Serving `<model>`**.

### 4. Chat as normal

Go to the **Chat** tab and chat with that model. Localy transparently routes requests for it to the pool — no special mode to select. A **🔗 N devices** badge appears in the chat header.

To stop, use **Stop pooled inference** on the Device Pool page.

---

## Live Contribution Analysis

While a model is served across the pool, Localy shows **which device is computing what** — using the real layer split, not a memory estimate:

- **In Chat:** click the **🔗 N devices** badge to expand a compact per-device split.
- **On the Device Pool page:** the **Live Contribution** card shows, for each device:
  - **Layer share %** — the portion of the model's layers it holds/computes.
  - **Idle detection** — a device that's connected but holding *no* layers for this model is flagged **idle** (its capacity is unused for this model).
  - **Role** — coordinator (your device) vs worker, plus address and memory.
  - **Balance verdict** — whether the split is efficient (layers track each device's memory), skewed (the most-loaded device may bottleneck speed), or wasteful (idle devices).

---

## How the split is decided

Localy's shard planner distributes layers roughly in proportion to each device's usable memory budget (adjusted by a compute score), so a device with more RAM holds more of the model. The plan is what you see in **Check fit** and **Live Contribution**. Combined throughput is bounded by the slowest link in the chain, which is why balance matters.

---

## Ports used

| Purpose | Default port | Setting |
|---|---|---|
| API server | `11434` | `LOCALY_PORT` |
| RPC worker (this device, when sharing) | `50052` | `LOCALY_RPC_PORT` |
| Pooled coordinator (llama-server) | `8080` | `LOCALY_COORDINATOR_PORT` |

See [Configuration](configuration.md) to change these. Make sure your firewall allows the RPC port on the LAN for devices that share.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Scan finds no devices | Helpers aren't sharing, or not on the same WiFi/hotspot. On each helper: **Share this device**, then scan again. |
| A device shows but won't join | Firewall blocking the RPC port (`50052`) on that device, or a wrong `host:port`. |
| Joined, but chat still uses one device | You haven't loaded the model across the pool — click **Run pooled**. Joining alone doesn't start inference. |
| "Does not fit" even with several devices | Combined memory is still short for that model/quant. Try a smaller quantization or add another device. |
| A device shows **idle** in Live Contribution | It's connected but holds no layers for this model (small model, or the planner placed all layers elsewhere). Fine for correctness; add larger models to use it. |
| Pooled generation is slower than solo | Expected if the model already fits on one device — network hops between layers add latency. Run it solo. |

More general help: [Troubleshooting](troubleshooting.md).
