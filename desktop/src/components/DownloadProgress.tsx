import React from "react";
import { ProgressStats } from "../lib/downloadTracker";
import { humanBytes, humanSpeed, humanTime } from "../lib/format";

interface Props {
  stats: ProgressStats | null;
  status?: string; // e.g. "pulling manifest", "verifying", "downloading"
  compact?: boolean; // smaller variant for the model catalog cards
}

/** Streaming download progress with speed, ETA, and completed/remaining analysis. */
export const DownloadProgress: React.FC<Props> = ({ stats, status, compact }) => {
  const pct = stats ? stats.percent : 0;
  const label = stats
    ? (status && status !== "downloading" ? status : "Downloading")
    : "Preparing transfer";

  return (
    <div style={styles.wrap}>
      <div style={styles.topRow}>
        <span style={styles.label}>{label}…</span>
        <span style={styles.pct}>{pct.toFixed(1)}%</span>
      </div>

      <div style={styles.barBg}>
        <div style={{ ...styles.barFill, width: `${pct}%` }} />
      </div>

      {stats && (
        <div style={compact ? styles.metaRowCompact : styles.metaGrid}>
          <Metric label="Downloaded" value={`${humanBytes(stats.completed)} / ${humanBytes(stats.total)}`} />
          <Metric label="Speed" value={humanSpeed(stats.speedBps)} />
          <Metric label="Time left" value={humanTime(stats.etaSeconds)} />
          {compact && <Metric label="Remaining" value={humanBytes(Math.max(0, stats.total - stats.completed))} />}
          {!compact && <Metric label="Elapsed" value={humanTime(stats.elapsedSeconds)} />}
          {!compact && (
            <Metric label="Remaining" value={humanBytes(Math.max(0, stats.total - stats.completed))} />
          )}
        </div>
      )}
    </div>
  );
};

const Metric: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div style={styles.metric}>
    <span style={styles.metricLabel}>{label}</span>
    <span style={styles.metricValue}>{value}</span>
  </div>
);

const styles: { [key: string]: React.CSSProperties } = {
  wrap: { width: "100%" },
  topRow: { display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "6px" },
  label: { fontSize: "13px", color: "#a1a1aa" },
  pct: { fontSize: "13px", color: "#e4e4e7", fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 },
  barBg: { width: "100%", height: "6px", background: "rgba(255,255,255,0.06)", borderRadius: "3px", overflow: "hidden" },
  barFill: {
    height: "100%",
    background: "linear-gradient(90deg, #6366f1 0%, #8b5cf6 100%)",
    borderRadius: "3px",
    transition: "width 0.25s ease-out",
  },
  metaGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))",
    gap: "10px",
    marginTop: "12px",
  },
  metaRowCompact: { display: "flex", gap: "14px", marginTop: "8px", flexWrap: "wrap" },
  metric: { display: "flex", flexDirection: "column", gap: "2px" },
  metricLabel: { fontSize: "10px", color: "#71717a", textTransform: "uppercase", letterSpacing: "0.04em" },
  metricValue: { fontSize: "13px", color: "#e4e4e7", fontFamily: "'JetBrains Mono', monospace" },
};
