import React, { useState, useEffect } from "react";
import { api } from "../api/endpoints";
import { PoolStatus, ShardPlan, DiscoveredWorker, RegistryModel } from "../api/types";

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

  useEffect(() => {
    refreshStatus();
    loadModels();
    const t = setInterval(refreshStatus, 5000);
    return () => clearInterval(t);
  }, []);

  const refreshStatus = async () => {
    try {
      setStatus(await api.getPoolStatus());
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
      setError(e.message);
    } finally {
      setBusy("");
    }
  };

  const runPooled = async () => {
    if (!selectedModel) return;
    setBusy("load");
    setError("");
    try {
      const p = await api.loadPooled(selectedModel);
      setPlan(p);
      refreshStatus();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy("");
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
            <select style={styles.select} value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)}>
              {models.map((m) => (
                <option key={m.id} value={m.id}>{m.name} ({m.parameter_count_billions.toFixed(1)}B)</option>
              ))}
            </select>
            <button className="btn btn-secondary" onClick={checkFit} disabled={busy === "fit"}>
              Check fit
            </button>
            <button className="btn btn-primary" onClick={runPooled} disabled={busy === "load" || !plan?.fits}>
              {busy === "load" ? "Starting…" : "Run pooled"}
            </button>
          </div>

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
};
