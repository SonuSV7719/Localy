import React from "react";

// Collapsible reasoning panel. Reasoning-model chain-of-thought is hidden by
// default so the chat shows only the final answer; users can expand it.

interface Props {
  thinking: string;
  inProgress: boolean;
}

export const ThinkingBlock: React.FC<Props> = ({ thinking, inProgress }) => {
  // Auto-expanded while streaming reasoning, auto-collapsed once the answer starts.
  const [open, setOpen] = React.useState(inProgress);
  React.useEffect(() => {
    if (!inProgress) setOpen(false);
  }, [inProgress]);

  if (!thinking) return null;

  return (
    <div style={styles.wrap}>
      <button type="button" style={styles.toggle} onClick={() => setOpen((o) => !o)}>
        <span style={{ transform: open ? "rotate(90deg)" : "none", transition: "transform 0.15s" }}>▶</span>
        {inProgress ? "Thinking…" : "Reasoning"}
        <span style={styles.hint}>{open ? "hide" : "show"}</span>
      </button>
      {open && <div style={styles.body}>{thinking}</div>}
    </div>
  );
};

const styles: { [key: string]: React.CSSProperties } = {
  wrap: { marginBottom: "10px" },
  toggle: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    fontSize: "12px",
    color: "#a1a1aa",
    background: "rgba(255,255,255,0.03)",
    border: "1px solid var(--panel-border)",
    borderRadius: "6px",
    padding: "5px 10px",
    cursor: "pointer",
  },
  hint: { marginLeft: "auto", fontSize: "11px", color: "#71717a" },
  body: {
    marginTop: "6px",
    padding: "10px 12px",
    fontSize: "13px",
    color: "#b4b4bc",
    lineHeight: 1.6,
    whiteSpace: "pre-wrap",
    borderLeft: "2px solid var(--panel-border)",
    background: "rgba(0,0,0,0.2)",
    borderRadius: "0 6px 6px 0",
  },
};
