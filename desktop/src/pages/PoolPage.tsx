import React, { useState, useEffect } from "react";
import { api } from "../api/endpoints";
import { PoolStatus, ShardPlan, DiscoveredWorker, RegistryModel } from "../api/types";
import { DeviceContribution } from "../components/DeviceContribution";
import { Activity, CheckCircle2, Handshake, Search, X, XCircle } from "lucide-react";

interface LocalModelOption {
  id: string;
  label: string;
}

export const PoolPage: React.FC = () => {
  const [status, setStatus] = useState<PoolStatus | null>(null);
  const [discovered, setDiscovered] = useState<DiscoveredWorker[]>([]);
  const [modelOptions, setModelOptions] = useState<LocalModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [plan, setPlan] = useState<ShardPlan | null>(null);
  const [busy, setBusy] = useState<string>("");
  const [manualAddr, setManualAddr] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [scanned, setScanned] = useState<boolean>(false);
  // Live layer split for the model currently served across the pool.
  const [livePlan, setLivePlan] = useState<ShardPlan | null>(null);
  const livePlanModelRef = React.useRef<string | null>(null);
  // "Run pooled" is kicked off on the server and tracked via status.loading, so
  // progress survives tab switches. `initiating` covers the brief gap between
  // clicking and the first status poll that reflects the load.
  const [initiating, setInitiating] = useState<boolean>(false);

  // Poll faster while a load is happening so the progress readout stays smooth,
  // slower otherwise. Because progress lives on the server, the banner comes
  // back correctly after switching tabs (this component just re-reads it).
  const loadingActive = !!status?.loading?.active || initiating;
  useEffect(() => {
    refreshStatus();
    loadModels();
    const t = setInterval(refreshStatus, loadingActive ? 800 : 4000);
    return () => clearInterval(t);
  }, [loadingActive]);

  // Human-readable phase label for the progress banner.
  const phaseLabel = (phase?: string): string => {
    switch (phase) {
      case "starting": return "Starting coordinator…";
      case "loading": return "Streaming model layers to devices…";
      case "ready": return "Ready";
      case "error": return "Failed";
      default: return "Preparing…";
    }
  };

  const fmtDuration = (secs?: number | null): string => {
    if (secs == null) return "—";
    const s = Math.round(secs);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    return `${m}m ${s % 60}s`;
  };

  const fmtBytes = (b?: number | null): string => {
    if (!b) return "—";
    const gb = b / 1024 ** 3;
    if (gb >= 1) return `${gb.toFixed(2)} GB`;
    return `${(b / 1024 ** 2).toFixed(0)} MB`;
  };

  // Turn backend errors into something a user can act on.
  const prettyPoolError = (e: any): string => {
    const msg = e?.message || String(e);
    if (e?.code === "timeout") {
      return "The request timed out on the client, but the pool may still be loading — watch the Pool Status above.";
    }
    if (/no remote workers/i.test(msg)) {
      return "No other devices in the pool yet. On another device, open Localy → Device Pool → “Share this device”, then Scan and Join it here first.";
    }
    if (/does not fit/i.test(msg)) {
      return `This model doesn't fit across the current pool. ${msg}`;
    }
    return msg;
  };

  const refreshStatus = async () => {
    try {
      const s = await api.getPoolStatus();
      setStatus(s);
      // Auto-load the live contribution analysis whenever a model is being
      // served across >1 device (refetched only when the active model changes).
      if (s.pooled_active && s.active_model && s.node_count > 1) {
        if (livePlanModelRef.current !== s.active_model) {
          livePlanModelRef.current = s.active_model;
          try {
            setLivePlan(await api.poolFit(s.active_model));
          } catch {
            setLivePlan(null);
          }
        }
      } else {
        livePlanModelRef.current = null;
        setLivePlan(null);
      }
    } catch {
      /* backend may be starting */
    }
  };

  const loadModels = async () => {
    try {
      const data = await api.getModels();
      const options = data.flatMap((m: RegistryModel) =>
        m.variants
          .filter((v) => v.is_downloaded)
          .map((v) => {
            const isDefault = v.quantization === m.default_variant;
            const id = isDefault ? m.id : `${m.id}-${v.quantization.toLowerCase()}`;
            return {
              id,
              label: `${m.name} (${m.parameter_count_billions.toFixed(1)}B) · ${v.quantization}`,
            };
          })
      );
      setModelOptions(options);
      if (options.length) {
        setSelectedModel((current) => options.some((o) => o.id === current) ? current : options[0].id);
      } else {
        setSelectedModel("");
      }
    } catch {
      /* ignore */
    }
  };

  const discover = async () => {
    setBusy("discover");
    setError("");
    try {
      const found = await api.discoverPool(false);
      setDiscovered(found);
      setScanned(true);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  };

  const joinAll = async () => {
    setBusy("joinall");
    setError("");
    try {
      for (const w of discovered) {
        await api.joinPool(w.host, w.port, w.label, w.budget_gb, w.metrics_port);
      }
      await refreshStatus();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  };

  const join = async (host: string, port: number, label = "", budgetGb?: number | null, metricsPort?: number | null) => {
    setError("");
    try {
      await api.joinPool(host, port, label, budgetGb, metricsPort);
      refreshStatus();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const joinManual = async () => {
    const [host, portStr] = manualAddr.split(":");
    const port = parseInt(portStr, 10);
    if (!host || !portStr || Number.isNaN(port) || port < 1 || port > 65535) {
      setError("Enter address as host:port (e.g. 192.168.1.5:50052)");
      return;
    }
    await join(host.trim(), port, "Manual");
    setManualAddr("");
  };

  const leave = async (nodeId: string) => {
    await api.leavePool(nodeId);
    refreshStatus();
  };

  const checkFit = async () => {
    if (!selectedModel) return;
    setBusy("fit");
    setError("");
    try {
      setPlan(await api.poolFit(selectedModel));
    } catch (e: any) {
      setError(prettyPoolError(e));
    } finally {
      setBusy("");
    }
  };

  const runPooled = async () => {
    if (!selectedModel) return;
    setError("");
    setInitiating(true);
    try {
      // Returns quickly now — the load runs on the server and we track it via
      // status.loading, so closing this tab won't stop it.
      const p = await api.loadPooled(selectedModel);
      setPlan(p);
      await refreshStatus();
    } catch (e: any) {
      setError(prettyPoolError(e));
    } finally {
      setInitiating(false);
    }
  };

  const stopPooled = async () => {
    setBusy("stop");
    try {
      await api.unloadPooled();
      refreshStatus();
    } finally {
      setBusy("");
    }
  };

  const toggleWorker = async () => {
    setBusy("worker");
    setError("");
    try {
      if (status?.worker_running) await api.stopWorker();
      else await api.startWorker();
      await refreshStatus();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  };

  return (
    <div style={styles.wrap}>
      <div style={styles.header} className="glass-panel">
        <h1 style={styles.title}>Device Pool</h1>
        <p style={styles.sub}>
          Combine your devices (and friends' — same WiFi or hotspot) to run models too large for one
          machine. Pooling unlocks <b>bigger</b> models; a model that fits on one device is faster solo.
        </p>
      </div>

      <div style={styles.body}>
        {error && <div style={styles.errorBox}>{error}</div>}

        {/* Pool status */}
        <div style={styles.card} className="glass-panel">
          <div style={styles.cardTitle}>
            Pool Status
            {status?.pooled_active && (
              <span style={styles.activeBadge}><Activity size={12} aria-hidden="true" /> Serving {status.active_model}</span>
            )}
          </div>
          {status ? (
            <>
              <div style={styles.statRow}>
                <span>{status.node_count} device(s)</span>
                <span>~{status.total_budget_gb.toFixed(1)} GB pooled memory</span>
              </div>
              <div style={styles.nodeList}>
                {status.nodes.map((n) => (
                  <div key={n.node_id} style={styles.node}>
                    <div>
                      <span style={styles.nodeLabel}>{n.label}</span>
                      {n.is_local && <span style={styles.localTag}>this device</span>}
                      {!n.is_local && n.online === false && <span style={styles.offlineTag}>reconnecting</span>}
                      <div style={styles.nodeAddr}>{n.address}</div>
                    </div>
                    <div style={styles.nodeRight}>
                      <span>{n.online === false ? "offline" : `~${n.budget_gb.toFixed(1)} GB`}</span>
                      {!n.is_local && (
                        <button className="btn btn-secondary" style={styles.smBtn} onClick={() => leave(n.node_id)}>
                          Remove
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
              {status.pooled_active && (
                <button className="btn btn-secondary" style={styles.wideBtn} onClick={stopPooled} disabled={busy === "stop"}>
                  Stop pooled inference
                </button>
              )}
            </>
          ) : (
            <p style={styles.muted}>Connecting to backend…</p>
          )}
        </div>

        {/* Live contribution analysis (only while a model is served pooled) */}
        {status?.pooled_active && livePlan && livePlan.nodes.length > 0 && (
          <div style={styles.card} className="glass-panel">
            <div style={styles.cardTitle}>
              Live Contribution
              <span style={styles.activeBadge}><Activity size={12} aria-hidden="true" /> Who computes what</span>
            </div>
            <DeviceContribution plan={livePlan} status={status} />
          </div>
        )}

        {/* Share this device */}
        <div style={styles.card} className="glass-panel">
          <div style={styles.cardTitle}>
            Share This Device
            {status?.worker_running && <span style={styles.activeBadge}><Activity size={12} aria-hidden="true" /> Sharing</span>}
          </div>
          <p style={styles.shareText}>
            Let other Localy devices on this network borrow this machine's memory/CPU.
            When on, this PC appears in your friends' pools automatically.
          </p>
          <button
            className={status?.worker_running ? "btn btn-secondary" : "btn btn-primary"}
            onClick={toggleWorker}
            disabled={busy === "worker"}
          >
            {busy === "worker"
              ? "…"
              : status?.worker_running
              ? "Stop sharing"
              : <><Handshake size={16} aria-hidden="true" /> Share this device</>}
          </button>
        </div>

        {/* Add devices */}
        <div style={styles.card} className="glass-panel">
          <div style={styles.cardTitle}>Add Devices</div>
          <div style={styles.rowGap}>
            <button className="btn btn-primary" onClick={discover} disabled={busy === "discover"}>
              {busy === "discover" ? "Scanning…" : <><Search size={16} aria-hidden="true" /> Scan WiFi/Hotspot</>}
            </button>
            <input
              style={styles.addrInput}
              placeholder="or enter host:port (e.g. 192.168.1.5:50052)"
              value={manualAddr}
              onChange={(e) => setManualAddr(e.target.value)}
            />
            <button className="btn btn-secondary" onClick={joinManual}>Add</button>
          </div>
          {discovered.length > 0 && (
            <>
              <div style={styles.scanResult}>
                Found {discovered.length} device{discovered.length > 1 ? "s" : ""}
                <button className="btn btn-primary" style={styles.smBtn} onClick={joinAll} disabled={busy === "joinall"}>
                  {busy === "joinall" ? "Joining…" : "Join all"}
                </button>
              </div>
              <div style={styles.nodeList}>
                {discovered.map((w) => {
                  const inPool = status?.nodes.some((n) => n.node_id === w.node_id || n.address === `${w.host}:${w.port}`);
                  return (
                    <div key={w.node_id} style={styles.node}>
                      <div>
                        <span style={styles.nodeLabel}>{w.label}</span>
                        <div style={styles.nodeAddr}>
                          {w.host}:{w.port}{w.budget_gb ? ` · ~${w.budget_gb.toFixed(1)} GB` : ""}
                        </div>
                      </div>
                      {inPool ? (
                        <span style={styles.joinedTag}><CheckCircle2 size={13} aria-hidden="true" /> in pool</span>
                      ) : (
                        <button className="btn btn-primary" style={styles.smBtn} onClick={() => join(w.host, w.port, w.label, w.budget_gb, w.metrics_port)}>
                          Join
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          )}
          {scanned && discovered.length === 0 && busy !== "discover" && (
            <div style={styles.emptyScan}>
              No devices found on your network. On each other device: open Localy →
              Device Pool → <b>Share this device</b> (or install the Android worker and tap Connect),
              and make sure everyone is on the <b>same WiFi or hotspot</b>. Then scan again.
            </div>
          )}
          <p style={styles.hint}>
            Add as many devices as you like — layers are split across all of them by memory.
            Each appears here automatically once it's sharing on the same network.
          </p>
        </div>

        {/* Run a model pooled */}
        <div style={styles.card} className="glass-panel">
          <div style={styles.cardTitle}>Run a Model Across the Pool</div>
          <div style={styles.rowGap}>
            <select
              style={styles.select}
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              disabled={loadingActive}
            >
              {modelOptions.length === 0 ? (
                <option value="">No downloaded model variants</option>
              ) : (
                modelOptions.map((m) => (
                  <option key={m.id} value={m.id}>{m.label}</option>
                ))
              )}
            </select>
            <button className="btn btn-secondary" onClick={checkFit} disabled={!selectedModel || busy === "fit" || loadingActive}>
              {busy === "fit" ? "Checking…" : "Check fit"}
            </button>
            <button
              className="btn btn-primary"
              onClick={runPooled}
              disabled={!selectedModel || loadingActive || (!!plan && !plan.fits)}
            >
              {loadingActive ? "Loading…" : "Run pooled"}
            </button>
          </div>

          {/* Live, server-tracked progress — survives tab switches */}
          {loadingActive && (() => {
            const load = status?.loading;
            const pct = load?.percent ?? null;
            const observed = load?.transfer_measurement === "observed_network";
            const estimated = load?.transfer_measurement === "estimated_from_loader";
            const hasTransferProgress = (observed || estimated) && load?.bytes_total != null && load.bytes_sent != null;
            const transferredBytes = hasTransferProgress ? load!.bytes_sent! : null;
            const totalTransferBytes = hasTransferProgress ? load!.bytes_total! : null;
            const plannedRemaining = hasTransferProgress
              ? Math.max(0, totalTransferBytes! - transferredBytes!)
              : null;
            const transferPct = totalTransferBytes && transferredBytes != null
              ? Math.min(100, (transferredBytes / totalTransferBytes) * 100)
              : null;
            return (
              <div style={styles.loadingBanner}>
                <div style={styles.loadingHeaderRow}>
                  <span className="pulse-indicator" style={styles.spinnerDot} />
                  <span style={styles.loadingTitle}>
                    Loading <b>{load?.model || selectedModel}</b> across {load?.node_count || status?.node_count || 1} device(s)
                  </span>
                  <span style={styles.loadingPhase}>{load?.stage || phaseLabel(load?.phase)}</span>
                </div>

                {/* Progress bar: real % if the loader reports it, else indeterminate */}
                <div style={styles.progressTrack}>
                  <div
                    style={{
                      ...styles.progressFill,
                      width: transferPct != null ? `${transferPct}%` : "100%",
                      opacity: transferPct != null ? 1 : 0.35,
                    }}
                    className={transferPct == null ? "pulse-indicator" : undefined}
                  />
                </div>

                <div style={styles.statGrid}>
                  <div style={styles.stat}><span style={styles.statLabel}>Received by workers</span>
                    {hasTransferProgress ? fmtBytes(load?.bytes_sent) : "Waiting for telemetry"}
                  </div>
                  <div style={styles.stat}><span style={styles.statLabel}>Planned weight transfer</span>
                    {load?.bytes_total ? fmtBytes(load.bytes_total) : "--"}
                  </div>
                  <div style={styles.stat}><span style={styles.statLabel}>Remaining (planned)</span>
                    {plannedRemaining != null ? fmtBytes(plannedRemaining) : "Not measurable yet"}
                  </div>
                  <div style={styles.stat}><span style={styles.statLabel}>Measured speed</span>
                    {hasTransferProgress ? (load?.speed_bps ? `${fmtBytes(load.speed_bps)}/s` : "Measuring...") : "Unavailable"}
                  </div>
                  <div style={styles.stat}><span style={styles.statLabel}>Time left (estimate)</span>{hasTransferProgress ? fmtDuration(load?.eta_s) : "Waiting for transfer"}</div>
                  <div style={{ display: "none" }}>
                  <div style={styles.stat}><span style={styles.statLabel}>Transferred {pct != null ? "(est.)" : ""}</span>
                    {load?.bytes_total ? `${fmtBytes(load?.bytes_sent)} / ${fmtBytes(load.bytes_total)}` : (pct != null ? `~${pct.toFixed(0)}%` : "working…")}
                  </div>
                  <div style={styles.stat}><span style={styles.statLabel}>Remaining</span>
                    {load?.bytes_total ? fmtBytes(Math.max(0, (load.bytes_total || 0) - (load?.bytes_sent || 0))) : "—"}
                  </div>
                  <div style={styles.stat}><span style={styles.statLabel}>Speed {load?.speed_bps ? "(est.)" : ""}</span>
                    {load?.speed_bps ? `${fmtBytes(load.speed_bps)}/s` : "measuring…"}
                  </div>
                  <div style={styles.stat}><span style={styles.statLabel}>Time left (est.)</span>{fmtDuration(load?.eta_s)}</div>
                  <div style={styles.stat}><span style={styles.statLabel}>Elapsed</span>{fmtDuration(load?.elapsed_s)}</div>
                  <div style={styles.stat}><span style={styles.statLabel}>Worker devices</span>{load?.remote_count ?? status?.remote_count ?? 0}</div>
                  </div>
                </div>

                {load?.bytes_total ? (
                  <>
                  <div style={styles.loadingSub}>
                    {observed
                      ? `Live worker network traffic is being measured. ${fmtBytes(load.bytes_total)} is the planned weight allocation; protocol overhead and a warm worker cache can make it differ from received bytes.`
                      : estimated
                        ? `No worker byte counter is available, so progress is estimated from llama.cpp load phases. ${fmtBytes(load.bytes_total)} is the planned weight allocation.`
                        : "This worker has not provided transfer telemetry yet. The loader phase is shown above while Localy waits for measurable progress."}
                  </div>
                  <div style={{ ...styles.loadingSub, display: "none" }}>
                    ~{fmtBytes(load.bytes_total)} of weights stream to {load?.remote_count || 1} worker device(s) over
                    the network. Transferred/speed/ETA are estimates derived from the loader's stage — llama.cpp
                    doesn't expose byte-exact RPC progress — so they refine as the load proceeds.
                  </div>
                  </>
                ) : null}
                {observed && (load?.transfer_idle_s ?? 0) > 12 && (
                  <div style={styles.stallNote}>
                    No worker data received for {fmtDuration(load?.transfer_idle_s)}. Check WiFi strength and keep the worker app open.
                  </div>
                )}
                {false && (load?.idle_s ?? 0) > 20 && (
                  <div style={styles.stallNote}>
                    ⏳ Still working — no update from the loader in {fmtDuration(load?.idle_s)}. Streaming weights to a
                    slow worker (e.g. a phone/tablet over WiFi) can take several minutes with no output.
                  </div>
                )}
                {load?.last_log && <div style={styles.logLine}>{load.last_log}</div>}
                <div style={styles.loadingActions}>
                  <button className="btn btn-secondary" style={styles.smBtn} onClick={stopPooled} disabled={busy === "stop"}>
                    {busy === "stop" ? "Cancelling…" : <><X size={14} aria-hidden="true" /> Cancel load</>}
                  </button>
                  <span style={styles.loadingHint}>You can switch tabs or close the window (background mode) — loading continues on the server.</span>
                </div>
              </div>
            );
          })()}

          {status?.loading?.phase === "error" && status.loading.error && !loadingActive && (
            <div style={styles.errorBanner}>
              <b>Pooled load failed.</b>
              <div style={styles.errorDetail}>{status.loading.error}</div>
            </div>
          )}

          {status?.pooled_active && (
            <div style={styles.successBanner}>
              <CheckCircle2 size={16} aria-hidden="true" /> <b>{status.active_model}</b> is now serving across the pool. Open the <b>Chat</b> tab and select
              this model to use it — requests route to the pool automatically.
            </div>
          )}

          {plan && (
            <div style={{ ...styles.planBox, borderColor: plan.fits ? "var(--semantic-success)" : "var(--semantic-error)" }}>
              <div style={{ ...styles.fitBadge, color: plan.fits ? "var(--semantic-success)" : "var(--semantic-error)" }}>
                {plan.fits
                  ? <><CheckCircle2 size={14} aria-hidden="true" /> Fits across the pool</>
                  : <><XCircle size={14} aria-hidden="true" /> Does not fit</>}
              </div>
              <p style={styles.planReason}>{plan.reason}</p>
              {plan.nodes.length > 0 && (
                <div style={styles.splitBars}>
                  {plan.nodes.map((n) => (
                    <div key={n.node_id} style={styles.splitRow}>
                      <span style={styles.splitLabel}>{n.label}</span>
                      <div style={styles.barBg}>
                        <div style={{ ...styles.barFill, width: `${n.layer_share_pct}%` }} />
                      </div>
                      <span style={styles.splitPct}>{n.layer_share_pct.toFixed(0)}%</span>
                    </div>
                  ))}
                </div>
              )}
              {plan.recommendations.map((r, i) => (
                <p key={i} style={styles.rec}>• {r}</p>
              ))}
            </div>
          )}
          {status?.pooled_active && (
            <p style={styles.hint}>
              This model is now served across the pool — chat with it from the <b>Chat</b> tab as usual.
            </p>
          )}
        </div>
      </div>
    </div>
  );
};

const styles: { [key: string]: React.CSSProperties } = {
  wrap: { display: "flex", flexDirection: "column", height: "100vh", width: "100%", background: "#09090b", overflow: "hidden" },
  header: { padding: "24px 30px", borderBottom: "1px solid var(--panel-border)", background: "rgba(10,10,15,0.3)" },
  title: { fontSize: "22px", color: "#fff", marginBottom: "6px" },
  sub: { fontSize: "13px", color: "#a1a1aa", maxWidth: "760px", lineHeight: 1.5 },
  body: { flexGrow: 1, overflowY: "auto", padding: "24px 30px", display: "flex", flexDirection: "column", gap: "20px" },
  errorBox: { background: "var(--semantic-error-bg)", border: "1px solid var(--semantic-error)", color: "#fca5a5", padding: "10px 14px", borderRadius: "8px", fontSize: "13px" },
  card: { borderRadius: "12px", padding: "20px 22px" },
  cardTitle: { fontSize: "15px", fontWeight: 600, color: "#fff", marginBottom: "14px", display: "flex", alignItems: "center", justifyContent: "space-between" },
  activeBadge: { display: "inline-flex", alignItems: "center", gap: "5px", fontSize: "12px", color: "var(--semantic-success)", fontWeight: 500 },
  statRow: { display: "flex", justifyContent: "space-between", fontSize: "13px", color: "#a1a1aa", marginBottom: "12px" },
  nodeList: { display: "flex", flexDirection: "column", gap: "8px", marginTop: "8px" },
  node: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 12px", background: "rgba(255,255,255,0.02)", border: "1px solid var(--panel-border)", borderRadius: "8px" },
  nodeLabel: { fontSize: "13px", fontWeight: 500, color: "#e4e4e7" },
  localTag: { fontSize: "10px", color: "#818cf8", marginLeft: "8px", textTransform: "uppercase" },
  offlineTag: { fontSize: "10px", color: "#fbbf24", marginLeft: "8px", textTransform: "uppercase" },
  nodeAddr: { fontSize: "11px", color: "#71717a", marginTop: "2px", fontFamily: "monospace" },
  nodeRight: { display: "flex", alignItems: "center", gap: "12px", fontSize: "12px", color: "#a1a1aa" },
  smBtn: { fontSize: "12px", padding: "5px 12px" },
  wideBtn: { width: "100%", marginTop: "14px", fontSize: "13px" },
  rowGap: { display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" },
  addrInput: { flexGrow: 1, minWidth: "220px", fontSize: "13px" },
  select: { minWidth: "220px", fontSize: "13px" },
  hint: { fontSize: "12px", color: "#71717a", marginTop: "12px", lineHeight: 1.5 },
  shareText: { fontSize: "13px", color: "#a1a1aa", marginBottom: "14px", lineHeight: 1.5 },
  scanResult: { display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: "14px", fontSize: "13px", color: "#e4e4e7", fontWeight: 500 },
  joinedTag: { display: "inline-flex", alignItems: "center", gap: "5px", fontSize: "12px", color: "var(--semantic-success)", fontWeight: 500 },
  emptyScan: { marginTop: "14px", padding: "12px 14px", background: "rgba(255,255,255,0.02)", border: "1px solid var(--panel-border)", borderRadius: "8px", fontSize: "12px", color: "#a1a1aa", lineHeight: 1.6 },
  muted: { fontSize: "13px", color: "#71717a" },
  planBox: { marginTop: "16px", padding: "16px", borderRadius: "10px", border: "1px solid", background: "rgba(255,255,255,0.02)" },
  fitBadge: { display: "inline-flex", alignItems: "center", gap: "6px", fontSize: "13px", fontWeight: 600, marginBottom: "8px" },
  planReason: { fontSize: "13px", color: "#d4d4d8", marginBottom: "12px", lineHeight: 1.5 },
  splitBars: { display: "flex", flexDirection: "column", gap: "8px", marginBottom: "10px" },
  splitRow: { display: "flex", alignItems: "center", gap: "10px" },
  splitLabel: { fontSize: "12px", color: "#a1a1aa", width: "120px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  barBg: { flexGrow: 1, height: "8px", background: "rgba(255,255,255,0.06)", borderRadius: "4px", overflow: "hidden" },
  barFill: { height: "100%", background: "var(--accent-gradient)", borderRadius: "4px" },
  splitPct: { fontSize: "11px", color: "#a1a1aa", width: "36px", textAlign: "right" },
  rec: { fontSize: "12px", color: "#a1a1aa", marginTop: "4px", lineHeight: 1.4 },
  loadingBanner: {
    display: "flex",
    flexDirection: "column",
    gap: "10px",
    marginTop: "16px",
    padding: "16px",
    borderRadius: "10px",
    background: "rgba(99,102,241,0.1)",
    border: "1px solid rgba(99,102,241,0.3)",
  },
  loadingHeaderRow: { display: "flex", alignItems: "center", gap: "10px" },
  spinnerDot: { width: "10px", height: "10px", borderRadius: "50%", background: "#818cf8", flexShrink: 0 },
  loadingTitle: { fontSize: "13px", color: "#e4e4e7", flexGrow: 1 },
  loadingPhase: { fontSize: "12px", color: "#818cf8", fontWeight: 500 },
  progressTrack: { height: "8px", background: "rgba(255,255,255,0.08)", borderRadius: "4px", overflow: "hidden" },
  progressFill: { height: "100%", background: "linear-gradient(90deg,#6366f1,#22c55e)", borderRadius: "4px", transition: "width 0.5s ease" },
  statGrid: { display: "flex", flexWrap: "wrap", gap: "18px" },
  stat: { display: "flex", flexDirection: "column", gap: "2px", fontSize: "13px", color: "#e4e4e7", fontVariantNumeric: "tabular-nums" },
  statLabel: { fontSize: "10px", color: "#71717a", textTransform: "uppercase", letterSpacing: "0.04em" },
  logLine: {
    fontSize: "11px",
    color: "#a1a1aa",
    fontFamily: "monospace",
    background: "rgba(0,0,0,0.3)",
    padding: "6px 10px",
    borderRadius: "6px",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  loadingSub: { fontSize: "12px", color: "#a1a1aa" },
  loadingHint: { fontSize: "11px", color: "#71717a" },
  stallNote: { fontSize: "12px", color: "#fbbf24", lineHeight: 1.5, padding: "6px 0" },
  loadingActions: { display: "flex", alignItems: "center", gap: "12px", marginTop: "6px", flexWrap: "wrap" },
  errorBanner: {
    marginTop: "16px",
    padding: "14px 16px",
    borderRadius: "10px",
    background: "var(--semantic-error-bg)",
    border: "1px solid var(--semantic-error)",
    fontSize: "13px",
    color: "#fca5a5",
  },
  errorDetail: { marginTop: "6px", fontSize: "11px", fontFamily: "monospace", whiteSpace: "pre-wrap", color: "#f0a0a0", maxHeight: "140px", overflowY: "auto" },
  successBanner: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    marginTop: "16px",
    padding: "14px 16px",
    borderRadius: "10px",
    background: "rgba(34,197,94,0.1)",
    border: "1px solid rgba(34,197,94,0.3)",
    fontSize: "13px",
    color: "#d4d4d8",
    lineHeight: 1.5,
  },
};
