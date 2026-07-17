import React, { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { enable, disable, isEnabled } from "@tauri-apps/plugin-autostart";

const RUN_BG_KEY = "localy_run_in_background";

/** Sync the persisted "run in background" preference to the Rust side. Called
 *  on app start (from App.tsx) so the window-close behaviour is correct even
 *  before the user visits this page. */
export async function syncBackgroundSetting(): Promise<void> {
  const enabled = localStorage.getItem(RUN_BG_KEY) === "true";
  try {
    await invoke("set_run_in_background", { enabled });
  } catch {
    /* not running under Tauri (e.g. plain web dev) */
  }
}

export const SettingsPage: React.FC = () => {
  const [runInBackground, setRunInBackground] = useState<boolean>(
    localStorage.getItem(RUN_BG_KEY) === "true"
  );
  const [autostart, setAutostart] = useState<boolean>(false);
  const [busy, setBusy] = useState<boolean>(false);
  const [note, setNote] = useState<string>("");

  useEffect(() => {
    isEnabled()
      .then(setAutostart)
      .catch(() => {});
  }, []);

  const toggleBackground = async (value: boolean) => {
    setRunInBackground(value);
    localStorage.setItem(RUN_BG_KEY, String(value));
    try {
      await invoke("set_run_in_background", { enabled: value });
    } catch {
      /* ignore in web dev */
    }
  };

  const toggleAutostart = async (value: boolean) => {
    setBusy(true);
    setNote("");
    try {
      if (value) await enable();
      else await disable();
      setAutostart(value);
    } catch (e: any) {
      setNote(`Could not change autostart: ${e?.message || e}`);
    } finally {
      setBusy(false);
    }
  };

  const quitApp = async () => {
    try {
      await invoke("quit_app");
    } catch {
      /* ignore */
    }
  };

  return (
    <div style={styles.page}>
      <h1 style={styles.h1}>Settings</h1>
      <p style={styles.sub}>Configure how Localy runs on this machine.</p>

      <div style={styles.card} className="glass-panel">
        <h2 style={styles.h2}>Background service</h2>

        <ToggleRow
          title="Keep running when window is closed"
          desc="Closing the window minimizes Localy to the system tray and keeps the local API server online (so pooled devices and API clients stay connected). Click the tray icon to reopen."
          checked={runInBackground}
          onChange={toggleBackground}
        />

        <ToggleRow
          title="Start Localy automatically on login"
          desc="Launch Localy in the background when you sign in to this computer."
          checked={autostart}
          disabled={busy}
          onChange={toggleAutostart}
        />

        {note && <div style={styles.note}>{note}</div>}

        <div style={styles.hintBox}>
          <strong>Tip:</strong> With both enabled, Localy behaves like a daemon — it runs on
          login and survives window closes. To fully stop it, use the tray icon → “Stop backend &amp;
          quit”, or the button below.
        </div>

        <button style={styles.quitBtn} onClick={quitApp}>
          Stop backend &amp; quit Localy
        </button>
      </div>
    </div>
  );
};

const ToggleRow: React.FC<{
  title: string;
  desc: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
}> = ({ title, desc, checked, disabled, onChange }) => (
  <div style={styles.row}>
    <div style={styles.rowText}>
      <div style={styles.rowTitle}>{title}</div>
      <div style={styles.rowDesc}>{desc}</div>
    </div>
    <button
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      style={{
        ...styles.switch,
        background: checked ? "var(--primary)" : "rgba(255,255,255,0.12)",
        opacity: disabled ? 0.5 : 1,
      }}
    >
      <span style={{ ...styles.knob, transform: checked ? "translateX(20px)" : "translateX(0)" }} />
    </button>
  </div>
);

const styles: { [key: string]: React.CSSProperties } = {
  page: { padding: "32px 40px", overflowY: "auto", height: "100%" },
  h1: { fontSize: "24px", fontWeight: 700, color: "#fff", margin: "0 0 6px" },
  sub: { color: "#71717a", fontSize: "14px", margin: "0 0 24px" },
  card: { maxWidth: "680px", padding: "24px", borderRadius: "12px", border: "1px solid var(--panel-border)" },
  h2: { fontSize: "16px", fontWeight: 600, color: "#fff", margin: "0 0 16px" },
  row: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "20px",
    padding: "14px 0",
    borderBottom: "1px solid var(--panel-border)",
  },
  rowText: { flexGrow: 1, minWidth: 0 },
  rowTitle: { fontSize: "14px", fontWeight: 500, color: "#e4e4e7", marginBottom: "4px" },
  rowDesc: { fontSize: "12px", color: "#71717a", lineHeight: 1.5 },
  switch: {
    width: "44px",
    height: "24px",
    borderRadius: "12px",
    border: "none",
    position: "relative",
    cursor: "pointer",
    flexShrink: 0,
    transition: "background 0.15s",
  },
  knob: {
    position: "absolute",
    top: "2px",
    left: "2px",
    width: "20px",
    height: "20px",
    borderRadius: "50%",
    background: "#fff",
    transition: "transform 0.15s",
  },
  note: { marginTop: "12px", fontSize: "12px", color: "#f87171" },
  hintBox: {
    marginTop: "18px",
    padding: "12px 14px",
    fontSize: "12px",
    color: "#a1a1aa",
    lineHeight: 1.6,
    background: "rgba(99,102,241,0.08)",
    border: "1px solid rgba(99,102,241,0.2)",
    borderRadius: "8px",
  },
  quitBtn: {
    marginTop: "18px",
    padding: "10px 16px",
    fontSize: "13px",
    color: "#f87171",
    background: "rgba(239,68,68,0.12)",
    border: "1px solid rgba(239,68,68,0.35)",
    borderRadius: "8px",
    cursor: "pointer",
  },
};
