import React, { useState, useEffect } from "react";
import { api } from "../api/endpoints";
import { AccessInfo } from "../api/types";
import { Activity, AlertTriangle, Check, Copy, Globe2, Plus } from "lucide-react";

export const ApiAccessPage: React.FC = () => {
  const [info, setInfo] = useState<AccessInfo | null>(null);
  const [newKey, setNewKey] = useState<string>("");
  const [label, setLabel] = useState<string>("");
  const [busy, setBusy] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [copied, setCopied] = useState<string>("");

  useEffect(() => {
    refresh();
  }, []);

  const refresh = async () => {
    try {
      setInfo(await api.getAccess());
    } catch (e: any) {
      setError(e.message);
    }
  };

  const copy = (text: string, tag: string) => {
    navigator.clipboard?.writeText(text);
    setCopied(tag);
    setTimeout(() => setCopied(""), 1500);
  };

  const genKey = async () => {
    setBusy("key");
    setError("");
    try {
      const r = await api.createKey(label || "API key");
      setNewKey(r.key);
      setLabel("");
      await refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  };

  const revoke = async (id: string) => {
    if (!confirm("Revoke this key? Anyone using it will lose access.")) return;
    await api.revokeKey(id);
    refresh();
  };

  const toggleTunnel = async () => {
    setBusy("tunnel");
    setError("");
    try {
      if (info?.tunnel.running) await api.stopTunnel();
      else await api.startTunnel();
      await refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  };

  const tunnelUrl = info?.tunnel.url || null;
  const exampleBase = tunnelUrl ? `${tunnelUrl}/v1` : info?.lan_url || "http://<this-pc>:11434/v1";
  const exampleKey = newKey || "lk_your_api_key";
  const curl = `curl ${exampleBase}/chat/completions \\
  -H "Authorization: Bearer ${exampleKey}" \\
  -H "Content-Type: application/json" \\
  -d '{"model":"llama3.2:3b","messages":[{"role":"user","content":"Hello"}]}'`;

  return (
    <div style={styles.wrap}>
      <div style={styles.header} className="glass-panel">
        <h1 style={styles.title}>API Access</h1>
        <p style={styles.sub}>
          Let apps and people use your models over the OpenAI-compatible API — on your
          network, or over the internet. Anyone with a valid key can connect; requests from
          this PC never need one.
        </p>
      </div>

      <div style={styles.body}>
        {error && <div style={styles.errorBox}>{error}</div>}

        {/* Endpoints */}
        <div style={styles.card} className="glass-panel">
          <div style={styles.cardTitle}>Endpoints</div>
          <Row label="On this network (LAN)" value={info?.lan_url || "…"} onCopy={() => copy(info?.lan_url || "", "lan")} copied={copied === "lan"} />
          <Row label="On this PC" value={info?.local_url || "…"} onCopy={() => copy(info?.local_url || "", "local")} copied={copied === "local"} />
          <p style={styles.hint}>
            OpenAI-compatible. Point any tool (Continue, LibreChat, an SDK) at the URL + a key.
          </p>
        </div>

        {/* Internet tunnel */}
        <div style={styles.card} className="glass-panel">
          <div style={styles.cardTitle}>
            Internet Access
            {info?.tunnel.running && <span style={styles.activeBadge}><Activity size={12} aria-hidden="true" /> Live</span>}
          </div>
          <p style={styles.sub2}>
            Expose your API to the internet via a Cloudflare tunnel — share the URL + a key with
            anyone, anywhere. (Free quick-tunnel: the URL changes each time and isn't for heavy
            production load.)
          </p>
          {tunnelUrl && (
            <Row label="Public URL" value={`${tunnelUrl}/v1`} onCopy={() => copy(`${tunnelUrl}/v1`, "tun")} copied={copied === "tun"} />
          )}
          <button
            className={info?.tunnel.running ? "btn btn-secondary" : "btn btn-primary"}
            onClick={toggleTunnel}
            disabled={busy === "tunnel"}
            style={{ marginTop: "12px" }}
          >
            {busy === "tunnel" ? "…" : info?.tunnel.running ? "Stop internet access" : <><Globe2 size={16} aria-hidden="true" /> Expose to the internet</>}
          </button>
        </div>

        {/* API keys */}
        <div style={styles.card} className="glass-panel">
          <div style={styles.cardTitle}>API Keys</div>
          <div style={styles.rowGap}>
            <input style={styles.input} placeholder="Key label (e.g. Alex's laptop)" value={label} onChange={(e) => setLabel(e.target.value)} />
            <button className="btn btn-primary" onClick={genKey} disabled={busy === "key"}>
              {busy === "key" ? "…" : <><Plus size={16} aria-hidden="true" /> Generate key</>}
            </button>
          </div>

          {newKey && (
            <div style={styles.newKeyBox}>
              <div style={styles.newKeyWarn}><AlertTriangle size={14} aria-hidden="true" /> Copy this key now — it won't be shown again.</div>
              <div style={styles.newKeyRow}>
                <code style={styles.newKeyCode}>{newKey}</code>
                <button className="btn btn-secondary" style={styles.copyBtn} onClick={() => copy(newKey, "new")}>
                  {copied === "new" ? <><Check size={14} aria-hidden="true" /> Copied</> : <><Copy size={14} aria-hidden="true" /> Copy</>}
                </button>
              </div>
            </div>
          )}

          <div style={styles.keyList}>
            {info?.keys.length === 0 && <p style={styles.hint}>No keys yet. Generate one to allow remote access.</p>}
            {info?.keys.map((k) => (
              <div key={k.id} style={styles.keyRow}>
                <div>
                  <span style={styles.keyLabel}>{k.label}</span>
                  <code style={styles.keyMasked}>{k.masked}</code>
                </div>
                <button className="btn btn-secondary" style={styles.copyBtn} onClick={() => revoke(k.id)}>Revoke</button>
              </div>
            ))}
          </div>
        </div>

        {/* Example */}
        <div style={styles.card} className="glass-panel">
          <div style={styles.cardTitle}>Example request</div>
          <pre style={styles.code}>{curl}</pre>
          <button className="btn btn-secondary" style={styles.copyBtn} onClick={() => copy(curl, "curl")}>
            {copied === "curl" ? <><Check size={14} aria-hidden="true" /> Copied</> : <><Copy size={14} aria-hidden="true" /> Copy</>}
          </button>
        </div>
      </div>
    </div>
  );
};

const Row: React.FC<{ label: string; value: string; onCopy: () => void; copied: boolean }> = ({ label, value, onCopy, copied }) => (
  <div style={styles.urlRow}>
    <span style={styles.urlLabel}>{label}</span>
    <code style={styles.urlValue}>{value}</code>
    <button className="btn btn-secondary" style={styles.copyBtn} onClick={onCopy}>
      {copied ? <><Check size={14} aria-hidden="true" /> Copied</> : <><Copy size={14} aria-hidden="true" /> Copy</>}
    </button>
  </div>
);

const styles: { [key: string]: React.CSSProperties } = {
  wrap: { display: "flex", flexDirection: "column", height: "100%", width: "100%", minWidth: 0, background: "#09090b", overflow: "hidden" },
  header: { padding: "24px 30px", borderBottom: "1px solid var(--panel-border)", background: "rgba(10,10,15,0.3)" },
  title: { fontSize: "22px", color: "#fff", marginBottom: "6px" },
  sub: { fontSize: "13px", color: "#a1a1aa", maxWidth: "780px", lineHeight: 1.5 },
  sub2: { fontSize: "13px", color: "#a1a1aa", lineHeight: 1.5, marginBottom: "10px" },
  body: { flexGrow: 1, overflowY: "auto", padding: "24px 30px", display: "flex", flexDirection: "column", gap: "20px" },
  errorBox: { background: "var(--semantic-error-bg)", border: "1px solid var(--semantic-error)", color: "#fca5a5", padding: "10px 14px", borderRadius: "8px", fontSize: "13px" },
  card: { borderRadius: "12px", padding: "20px 22px" },
  cardTitle: { fontSize: "15px", fontWeight: 600, color: "#fff", marginBottom: "14px", display: "flex", alignItems: "center", justifyContent: "space-between" },
  activeBadge: { display: "inline-flex", alignItems: "center", gap: "5px", fontSize: "12px", color: "var(--semantic-success)", fontWeight: 500 },
  urlRow: { display: "flex", alignItems: "center", gap: "10px", marginBottom: "8px" },
  urlLabel: { fontSize: "12px", color: "#71717a", width: "160px", flexShrink: 0 },
  urlValue: { flexGrow: 1, fontSize: "12px", color: "#e4e4e7", fontFamily: "'JetBrains Mono', monospace", background: "rgba(255,255,255,0.03)", padding: "6px 10px", borderRadius: "6px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  rowGap: { display: "flex", gap: "10px", alignItems: "center" },
  input: { flexGrow: 1, fontSize: "13px" },
  newKeyBox: { marginTop: "14px", padding: "14px", background: "rgba(139,92,246,0.06)", border: "1px solid rgba(139,92,246,0.3)", borderRadius: "8px" },
  newKeyWarn: { display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", color: "#c4b5fd", marginBottom: "8px" },
  newKeyRow: { display: "flex", alignItems: "center", gap: "10px" },
  newKeyCode: { flexGrow: 1, fontSize: "13px", color: "#fff", fontFamily: "'JetBrains Mono', monospace", wordBreak: "break-all" },
  keyList: { display: "flex", flexDirection: "column", gap: "8px", marginTop: "14px" },
  keyRow: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 12px", background: "rgba(255,255,255,0.02)", border: "1px solid var(--panel-border)", borderRadius: "8px" },
  keyLabel: { fontSize: "13px", color: "#e4e4e7", marginRight: "10px" },
  keyMasked: { fontSize: "12px", color: "#71717a", fontFamily: "'JetBrains Mono', monospace" },
  copyBtn: { fontSize: "12px", padding: "6px 12px", flexShrink: 0 },
  hint: { fontSize: "12px", color: "#71717a", marginTop: "10px", lineHeight: 1.5 },
  code: { background: "rgba(0,0,0,0.4)", border: "1px solid var(--panel-border)", borderRadius: "8px", padding: "14px", fontSize: "12px", color: "#e4e4e7", overflowX: "auto", marginBottom: "10px", whiteSpace: "pre-wrap" },
};
