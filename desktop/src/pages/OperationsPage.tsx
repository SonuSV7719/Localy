import React, { useEffect, useState } from "react";
import { api } from "../api/endpoints";
import { PoolOperations } from "../api/types";

const bytes = (n: number | null | undefined) =>
  n == null ? "Awaiting telemetry" : n >= 1024 ** 3 ? `${(n / 1024 ** 3).toFixed(2)} GB` : `${(n / 1024 ** 2).toFixed(0)} MB`;

const measurement = (m?: string) =>
  m === "observed_network" ? "observed" : m === "estimated_from_loader" ? "estimated" : "waiting";

export const OperationsPage: React.FC = () => {
  const [data, setData] = useState<PoolOperations | null>(null);
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    const load = async () => {
      try {
        setData(await api.getPoolOperations());
        setFallback(false);
      } catch {
        try {
          setData({ status: await api.getPoolStatus(), events: [], model_size_bytes: null });
          setFallback(true);
        } catch {
          setFallback(true);
        }
      }
    };
    load();
    const id = setInterval(load, 1000);
    return () => clearInterval(id);
  }, []);

  if (!data) {
    return <main style={s.page}><h1 style={s.h1}>Pool Operations</h1><p style={s.sub}>Backend is reconnecting. Device controls remain available in Device Pool.</p></main>;
  }

  const { status, events } = data;
  return <main style={s.page}>
    <h1 style={s.h1}>Pool Operations</h1>
    <p style={s.sub}>{fallback ? "Live status is available. Install the matching desktop update to enable the coordination timeline." : status.active_model ? `Serving ${status.active_model}` : "No pooled model is serving"}</p>

    <section style={s.summary}>
      <span>Coordinator: <b>{status.nodes.find(n => n.is_local)?.label || "This device"}</b></span>
      <span>Devices: <b>{status.online_count ?? status.node_count} online / {status.offline_count ?? 0} reconnecting</b></span>
      <span>Capacity: <b>{status.total_budget_gb.toFixed(2)} GB online</b></span>
      <span>State: <b>{status.loading?.phase || "idle"}</b></span>
    </section>

    <h2 style={s.h2}>Device Topology</h2>
    <section style={s.table}>
      {status.nodes.map((node: any) => (
        <div key={node.node_id} style={{ ...s.row, opacity: node.online === false ? 0.62 : 1 }}>
          <div><b>{node.label}</b><small>{node.is_local ? "Coordinator / local execution" : `${node.online === false ? "Reconnecting worker" : "Remote worker"} - ${node.address}`}</small></div>
          <div><label>Assigned layers</label><b>{node.online === false ? "offline" : `${node.planned_layer_share_pct ?? 0}%`}</b><div style={s.bar}><i style={{ ...s.fill, width: `${node.online === false ? 0 : node.planned_layer_share_pct ?? 0}%` }} /></div></div>
          <div><label>Planned model memory</label><b>{node.online === false ? "not counted" : bytes(node.planned_model_bytes)}</b><small>Planned allocation</small></div>
          <div><label>Memory offered</label><b>{node.budget_gb.toFixed(2)} GB</b><small>{node.online === false ? "Waiting for heartbeat" : "Worker capacity"}</small></div>
        </div>
      ))}
    </section>

    <h2 style={s.h2}>Transfer Telemetry</h2>
    <section style={s.summary}>
      <span>Transferred: <b>{bytes(status.loading?.bytes_sent)}</b></span>
      <span>Planned transfer: <b>{bytes(status.loading?.bytes_total)}</b></span>
      <span>Speed: <b>{status.loading?.speed_bps ? `${(status.loading.speed_bps / 1048576).toFixed(2)} MB/s` : "Awaiting telemetry"}</b></span>
      <span>ETA: <b>{status.loading?.eta_s == null ? "Awaiting telemetry" : `${Math.ceil(status.loading.eta_s)} sec`}</b></span>
      <span>Source: <b>{measurement(status.loading?.transfer_measurement)}</b></span>
    </section>

    <h2 style={s.h2}>Coordination Timeline</h2>
    <section style={s.timeline}>{events.length ? events.map(e => <div key={`${e.at}-${e.kind}`} style={s.event}><time>{new Date(e.at * 1000).toLocaleTimeString()}</time><div><b>{e.message}</b><small>{e.kind}</small></div></div>) : <p>No coordination events recorded in this backend session.</p>}</section>
  </main>;
};

const s: { [key: string]: React.CSSProperties } = {
  page: { height: "100%", overflowY: "auto", padding: "28px 32px", color: "#e4e4e7" },
  h1: { margin: 0, fontSize: 24 },
  sub: { color: "#a1a1aa", margin: "6px 0 20px" },
  h2: { fontSize: 16, margin: "28px 0 10px" },
  summary: { display: "flex", gap: 24, flexWrap: "wrap", padding: 14, border: "1px solid var(--panel-border)" },
  table: { border: "1px solid var(--panel-border)" },
  row: { display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr 1fr", gap: 18, padding: 16, borderBottom: "1px solid var(--panel-border)" },
  bar: { height: 6, background: "rgba(255,255,255,.1)", marginTop: 6 },
  fill: { display: "block", height: "100%", background: "#6366f1" },
  timeline: { borderLeft: "2px solid #6366f1", paddingLeft: 18 },
  event: { display: "flex", gap: 16, padding: "10px 0" },
};
