import React from "react";
import { ShardPlan, PoolStatus } from "../api/types";

// Renders the live per-device contribution for a model served across the pool.
// Uses the shard plan's real layer split (layer_share_pct) — i.e. which device
// actually holds/computes what — rather than a raw memory proxy. Shared between
// the chat header (compact) and the Device Pool page (full analysis).

interface Props {
  plan: ShardPlan;
  status?: PoolStatus | null;
  compact?: boolean;
}

// A device holding no layers is connected but not contributing to this model.
const isIdle = (pct: number) => pct < 0.5;

// Rough "is the split balanced vs each device's capacity?" verdict. If a
// device's layer share wildly exceeds its share of pooled memory, it's a
// bottleneck; if devices are idle, capacity is wasted.
function balanceVerdict(plan: ShardPlan): { level: "good" | "ok" | "warn"; text: string } {
  const active = plan.nodes.filter((n) => !isIdle(n.layer_share_pct));
  const idleCount = plan.nodes.length - active.length;
  const totalBudget = plan.nodes.reduce((s, n) => s + (n.budget_gb || 0), 0) || 1;

  let worstSkew = 0;
  for (const n of active) {
    const memShare = ((n.budget_gb || 0) / totalBudget) * 100;
    if (memShare > 0) worstSkew = Math.max(worstSkew, Math.abs(n.layer_share_pct - memShare));
  }

  if (idleCount > 0) {
    return { level: "warn", text: `${idleCount} connected device(s) idle — not holding any layers for this model.` };
  }
  if (worstSkew > 25) {
    return { level: "ok", text: "Split is uneven relative to device memory; the most-loaded device may bottleneck speed." };
  }
  return { level: "good", text: "Layers are balanced across devices in proportion to their memory — an efficient split." };
}

export const DeviceContribution: React.FC<Props> = ({ plan, status, compact }) => {
  const nodes = [...plan.nodes].sort((a, b) => b.layer_share_pct - a.layer_share_pct);
  if (nodes.length === 0) return null;
  const verdict = balanceVerdict(plan);
  const verdictColor =
    verdict.level === "good" ? "#4ade80" : verdict.level === "ok" ? "#fbbf24" : "#f87171";

  return (
    <div style={compact ? styles.compactWrap : styles.wrap}>
      <div style={styles.head}>
        {compact
          ? `Distributed across ${nodes.length} devices · ${plan.total_budget_gb.toFixed(1)} GB combined`
          : `Serving across ${nodes.length} devices · ${plan.total_budget_gb.toFixed(1)} GB pooled memory`}
      </div>

      {nodes.map((n) => {
        const idle = isIdle(n.layer_share_pct);
        return (
          <div key={n.node_id} style={styles.row}>
            <div style={styles.labelCol}>
              <span style={styles.label}>
                {n.is_local ? "🖥 This device" : `💻 ${n.label || n.address}`}
              </span>
              {!compact && (
                <span style={styles.meta}>
                  {n.is_local ? "coordinator" : "worker"} · {n.address} · ~{(n.budget_gb || 0).toFixed(1)} GB
                </span>
              )}
            </div>
            <div style={styles.barTrack}>
              <div
                style={{
                  ...styles.barFill,
                  width: `${Math.max(n.layer_share_pct, idle ? 0 : 2)}%`,
                  background: idle ? "rgba(255,255,255,0.15)" : "linear-gradient(90deg, #6366f1, #22c55e)",
                }}
              />
            </div>
            <span style={styles.pct}>
              {idle ? <span style={styles.idle}>idle</span> : `${n.layer_share_pct.toFixed(0)}%`}
            </span>
          </div>
        );
      })}

      {!compact && (
        <>
          <div style={{ ...styles.verdict, color: verdictColor, borderColor: verdictColor + "55" }}>
            {verdict.text}
          </div>
          {status?.pooled_active && status.active_model && (
            <div style={styles.servingLine}>Active model: <b>{status.active_model}</b></div>
          )}
        </>
      )}
      {compact && verdict.level !== "good" && (
        <div style={{ ...styles.compactVerdict, color: verdictColor }}>{verdict.text}</div>
      )}
    </div>
  );
};

const styles: { [key: string]: React.CSSProperties } = {
  compactWrap: { padding: "12px 24px", borderBottom: "1px solid var(--panel-border)", background: "rgba(10,10,15,0.3)" },
  wrap: {},
  head: { fontSize: "12px", color: "#a1a1aa", marginBottom: "10px" },
  row: { display: "flex", alignItems: "center", gap: "10px", marginBottom: "8px" },
  labelCol: { width: "200px", flexShrink: 0, display: "flex", flexDirection: "column", gap: "2px" },
  label: { fontSize: "12px", color: "#e4e4e7", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" },
  meta: { fontSize: "10px", color: "#71717a", fontFamily: "monospace", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" },
  barTrack: { flexGrow: 1, height: "8px", background: "rgba(255,255,255,0.06)", borderRadius: "4px", overflow: "hidden" },
  barFill: { height: "100%", borderRadius: "4px", transition: "width 0.3s" },
  pct: { fontSize: "12px", color: "#a1a1aa", width: "44px", textAlign: "right" },
  idle: { color: "#71717a", fontStyle: "italic", fontSize: "11px" },
  verdict: { marginTop: "12px", padding: "8px 12px", fontSize: "12px", lineHeight: 1.5, border: "1px solid", borderRadius: "8px", background: "rgba(255,255,255,0.02)" },
  compactVerdict: { marginTop: "6px", fontSize: "11px", lineHeight: 1.4 },
  servingLine: { marginTop: "8px", fontSize: "11px", color: "#71717a" },
};
