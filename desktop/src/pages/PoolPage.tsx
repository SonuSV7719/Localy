import React, { useState, useEffect } from "react";
import { api } from "../api/endpoints";
import { PoolStatus, ShardPlan, DiscoveredWorker, RegistryModel } from "../api/types";
import { DeviceContribution } from "../components/DeviceContribution";

export const PoolPage: React.FC = () => {
  const [status, setStatus] = useState<PoolStatus | null>(null);
  const [discovered, setDiscovered] = useState<DiscoveredWorker[]>([]);
  const [models, setModels] = useState<RegistryModel[]>([]);
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
    const t = setInterval(refreshStatus, loadingActive ? 1500 : 4000);
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
      setModels(data);
      if (data.length && !selectedModel) setSelectedModel(data[0].id);
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
        await api.joinPool(w.host, w.port, w.label);
      }
      await refreshStatus();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  };

  const join = async (host: string, port: number, label = "") => {
    setError("");
    try {
      await api.joinPool(host, port, label);
      refreshStatus();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const joinManual = async () => {
    if (!manualAddr.includes(":")) {
      setError("Enter address as host:port");
      return;
    }
    const [host, port] = manualAddr.split(":");
    await join(host, parseInt(port, 10), "Manual");
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
              <span style={styles.activeBadge}>● Serving {status.active_model}</span>
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
                      <div style={styles.nodeAddr}>{n.address}</div>
                    </div>
                    <div style={styles.nodeRight}>
                      <span>~{n.budget_gb.toFixed(1)} GB</span>
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
              <span style={styles.activeBadge}>● Who computes what</span>
            </div>
            <DeviceContribution plan={livePlan} status={status} />
          </div>
        )}

        {/* Share this device */}
        <div style={styles.card} className="glass-panel">
          <div style={styles.cardTitle}>
            Share This Device
            {status?.worker_running && <span style={styles.activeBadge}>● Sharing</span>}
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
              : "🤝 Share this device"}
          </button>
        </div>

        {/* Add devices */}
        <div style={styles.card} className="glass-panel">
          <div style={styles.cardTitle}>Add Devices</div>
          <div style={styles.rowGap}>
            <button className="btn btn-primary" onClick={discover} disabled={busy === "discover"}>
              {busy === "discover" ? "Scanning…" : "🔍 Scan WiFi/Hotspot"}
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
                        <span style={styles.joinedTag}>✓ in pool</span>
                      ) : (
                        <button className="btn btn-primary" style={styles.smBtn} onClick={() => join(w.host, w.port, w.label)}>
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
              {models.map((m) => (
                <option key={m.id} value={m.id}>{m.name} ({m.parameter_count_billions.toFixed(1)}B)</option>
              ))}
            </select>
            <button className="btn btn-secondary" onClick={checkFit} disabled={busy === "fit" || loadingActive}>
              {busy === "fit" ? "Checking…" : "Check fit"}
            </button>
            <button
              className="btn btn-primary"
              onClick={runPooled}
              disabled={loadingActive || (!!plan && !plan.fits)}
            >
              {loadingActive ? "Loading…" : "Run pooled"}
            </button>
          </div>

          {/* Live, server-tracked progress — survives tab switches */}
          {loadingActive && (() => {
            const load = status?.loading;
            const pct = load?.percent ?? null;
            return (
              <div style={styles.loadingBanner}>
                <div style={styles.loadingHeaderRow}>
                  <span className="pulse-indicator" style={styles.spinnerDot} />
                  <span style={styles.loadingTitle}>
                    Loading <b>{load?.model || selectedModel}</b> across {load?.node_count || status?.node_count || 1} device(s)
                  </span>
                  <span style={styles.loadingPhase}>{phaseLabel(load?.phase)}</span>
                </div>

                {/* Progress bar: real % if the loader reports it, else indeterminate */}
                <div style={styles.progressTrack}>
                  <div
                    style={{
                      ...styles.progressFill,
                      width: pct != null ? `${pct}%` : "100%",
                      opacity: pct != null ? 1 : 0.35,
                    }}
                    className={pct == null ? "pulse-indicator" : undefined}
                  />
                </div>

                <div style={styles.statGrid}>
                  <div style={styles.stat}><span style={styles.statLabel}>Progress</span>{pct != null ? `${pct.toFixed(0)}%` : "working…"}</div>
                  <div style={styles.stat}><span style={styles.statLabel}>Elapsed</span>{fmtDuration(load?.elapsed_s)}</div>
                  <div style={styles.stat}><span style={styles.statLabel}>ETA</span>{load?.eta_s != null ? fmtDuration(load.eta_s) : "estimating…"}</div>
                  <div style={styles.stat}>
                    <span style={styles.statLabel}>Transferred</span>
                    {load?.bytes_total ? `${fmtBytes(load.bytes_sent)} / ${fmtBytes(load.bytes_total)}` : "—"}
                  </div>
                  <div style={styles.stat}><span style={styles.statLabel}>Worker devices</span>{load?.remote_count ?? status?.remote_count ?? 0}</div>
                </div>

                {load?.bytes_total ? (
                  <div style={styles.loadingSub}>
                    ~{fmtBytes(load.bytes_total)} of model weights stream to {load?.remote_count || 1} worker device(s).
                  </div>
                ) : null}
                {load?.last_log && <div style={styles.logLine}>{load.last_log}</div>}
                <div style={styles.loadingHint}>You can switch tabs or close the window (with background mode on) — loading continues on the server.</div>
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
              ✅ <b>{status.active_model}</b> is now serving across the pool. Open the <b>Chat</b> tab and select
              this model to use it — requests route to the pool automatically.
            </div>
          )}

          {plan && (
            <div style={{ ...styles.planBox, borderColor: plan.fits ? "var(--semantic-success)" : "var(--semantic-error)" }}>
              <div style={{ ...styles.fitBadge, color: plan.fits ? "var(--semantic-success)" : "var(--semantic-error)" }}>
                {plan.fits ? "✅ Fits across the pool" : "❌ Does not fit"}
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
  activeBadge: { fontSize: "12px", color: "var(--semantic-success)", fontWeight: 500 },
  statRow: { display: "flex", justifyContent: "space-between", fontSize: "13px", color: "#a1a1aa", marginBottom: "12px" },
  nodeList: { display: "flex", flexDirection: "column", gap: "8px", marginTop: "8px" },
  node: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 12px", background: "rgba(255,255,255,0.02)", border: "1px solid var(--panel-border)", borderRadius: "8px" },
  nodeLabel: { fontSize: "13px", fontWeight: 500, color: "#e4e4e7" },
  localTag: { fontSize: "10px", color: "#818cf8", marginLeft: "8px", textTransform: "uppercase" },
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
  joinedTag: { fontSize: "12px", color: "var(--semantic-success)", fontWeight: 500 },
  emptyScan: { marginTop: "14px", padding: "12px 14px", background: "rgba(255,255,255,0.02)", border: "1px solid var(--panel-border)", borderRadius: "8px", fontSize: "12px", color: "#a1a1aa", lineHeight: 1.6 },
  muted: { fontSize: "13px", color: "#71717a" },
  planBox: { marginTop: "16px", padding: "16px", borderRadius: "10px", border: "1px solid", background: "rgba(255,255,255,0.02)" },
  fitBadge: { fontSize: "13px", fontWeight: 600, marginBottom: "8px" },
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
