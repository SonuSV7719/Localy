import React, { useState, useEffect, useRef } from "react";
import { api } from "../api/endpoints";
import { RegistryModel } from "../api/types";
import { DownloadProgress } from "../components/DownloadProgress";
import { ProgressStats } from "../lib/downloadTracker";

export const ModelsPage: React.FC = () => {
  const [models, setModels] = useState<RegistryModel[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  
  // Track currently selected variant per model by model ID
  // e.g. { "smollm2:2b": "Q4_K_M" }
  const [selectedQuants, setSelectedQuants] = useState<{ [modelId: string]: string }>({});

  // Dynamic Fit Assessments per model ID + Quant

  // Download status state: smoothed stats + status per model id.
  const [downloads, setDownloads] = useState<{
    [modelId: string]: { stats: ProgressStats | null; status: string };
  }>({});
  const startTimes = useRef<{ [modelId: string]: number }>({});
  const refreshed = useRef<Set<string>>(new Set());

  // Hugging Face search / add state
  const [hfQuery, setHfQuery] = useState<string>("");
  const [hfResults, setHfResults] = useState<{ id: string; downloads: number; likes: number }[]>([]);
  const [hfBusy, setHfBusy] = useState<string>("");
  const [hfSearched, setHfSearched] = useState<boolean>(false);
  const [showResults, setShowResults] = useState<boolean>(false);
  const searchBoxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    fetchCatalog();
    // Poll server-side download progress. Downloads run in the backend, so this
    // keeps working across tab switches — leaving/returning just resumes the view.
    const timer = setInterval(pollDownloads, 1500);
    return () => clearInterval(timer);
  }, []);

  // Close the search-results dropdown when clicking outside of it or pressing Esc.
  useEffect(() => {
    if (!showResults) return;
    const onDown = (e: MouseEvent) => {
      if (searchBoxRef.current && !searchBoxRef.current.contains(e.target as Node)) {
        setShowResults(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowResults(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [showResults]);

  const pollDownloads = async () => {
    try {
      const dls = await api.getDownloads();
      const next: { [id: string]: { stats: ProgressStats | null; status: string } } = {};
      const finished: string[] = [];
      for (const d of dls) {
        if (d.status === "downloading") {
          const speedBps = d.speed_mbps * 1024 * 1024;
          const eta = speedBps > 0 && d.total ? (d.total - d.completed) / speedBps : Infinity;
          const start = startTimes.current[d.model_id] || Date.now();
          next[d.model_id] = {
            status: "downloading",
            stats: {
              completed: d.completed,
              total: d.total,
              percent: d.total ? (d.completed / d.total) * 100 : 0,
              speedBps,
              etaSeconds: eta,
              elapsedSeconds: (Date.now() - start) / 1000,
            },
          };
        } else if (!refreshed.current.has(d.model_id)) {
          refreshed.current.add(d.model_id);
          finished.push(d.status === "error" ? `error:${d.error}` : d.status);
        }
      }
      setDownloads(next);
      if (finished.length) {
        finished.forEach((f) => f.startsWith("error:") && alert(`Download failed: ${f.slice(6)}`));
        fetchCatalog();
      }
    } catch {
      /* backend momentarily unreachable */
    }
  };

  const searchHF = async () => {
    if (!hfQuery.trim()) return;
    setHfBusy("search");
    setShowResults(true);
    setHfSearched(false);
    try {
      setHfResults(await api.searchCatalog(hfQuery));
      setHfSearched(true);
    } catch (e: any) {
      alert(`Search failed: ${e.message}`);
    } finally {
      setHfBusy("");
    }
  };

  const addHF = async (repoId: string) => {
    setHfBusy(repoId);
    try {
      const r = await api.addCatalogModel(repoId);
      if (r.error) alert(r.error);
      else await fetchCatalog(); // new model (with all its variants) appears in the grid
    } catch (e: any) {
      alert(`Add failed: ${e.message}`);
    } finally {
      setHfBusy("");
    }
  };

  // Fetch complete catalog of models
  const fetchCatalog = async () => {
    setLoading(true);
    try {
      const data = await api.getModels();
      setModels(data);

      // Default the selected quant per model (fit is read per-variant from the
      // response — each variant already carries its own real-size fit_level).
      const quants: { [modelId: string]: string } = {};
      for (const m of data) {
        if (m.variants.length > 0) {
          const downloadedVar = m.variants.find(v => v.is_downloaded);
          quants[m.id] = downloadedVar ? downloadedVar.quantization : m.variants[0].quantization;
        }
      }
      setSelectedQuants(quants);
    } catch (e) {
      console.error("Failed to fetch model catalog:", e);
    } finally {
      setLoading(false);
    }
  };

  // Handle dropdown quant changes (fit is per-variant, already in `models`).
  const handleQuantChange = (modelId: string, quant: string) => {
    setSelectedQuants({ ...selectedQuants, [modelId]: quant });
  };

  // Start a background download (runs server-side; keeps going across tabs).
  const handleDownload = async (modelId: string) => {
    startTimes.current[modelId] = Date.now();
    refreshed.current.delete(modelId);
    setDownloads((prev) => ({ ...prev, [modelId]: { stats: null, status: "downloading" } }));
    try {
      await api.startDownload(modelId);
      pollDownloads();
    } catch (e: any) {
      alert(`Couldn't start download: ${e.message}`);
      setDownloads((prev) => {
        const next = { ...prev };
        delete next[modelId];
        return next;
      });
    }
  };

  // Cancel an in-progress background download (partial kept for resume).
  const handleCancelDownload = async (modelId: string) => {
    await api.cancelDownload(modelId);
    pollDownloads();
  };

  // Delete model
  const handleDelete = async (modelId: string) => {
    const quant = selectedQuants[modelId];
    if (!quant) return;

    if (!confirm(`Are you sure you want to delete the local files for ${modelId}?`)) return;

    try {
      await api.deleteModel(modelId);
      fetchCatalog();
    } catch (e: any) {
      alert(`Delete failed: ${e.message}`);
    }
  };

  // Fit levels styling helper
  const getBadgeStyle = (level: string) => {
    switch (level) {
      case "fits_well":
        return {
          background: "var(--semantic-success-bg)",
          borderColor: "var(--semantic-success)",
          color: "var(--semantic-success)"
        };
      case "fits_tight":
        return {
          background: "var(--semantic-warning-bg)",
          borderColor: "var(--semantic-warning)",
          color: "var(--semantic-warning)"
        };
      case "does_not_fit":
        default:
        return {
          background: "var(--semantic-error-bg)",
          borderColor: "var(--semantic-error)",
          color: "var(--semantic-error)"
        };
    }
  };

  const getFitText = (level: string) => {
    switch (level) {
      case "fits_well": return "Fits Well";
      case "fits_tight": return "Tight Fit";
      case "does_not_fit": return "Needs Pooling";
      default: return "Unknown";
    }
  };

  return (
    <div style={styles.catalogWrapper}>
      
      {/* Catalog Header */}
      <div style={styles.header} className="glass-panel">
        <h1 style={styles.headerTitle}>Model Catalog</h1>
        <p style={styles.headerSub}>
          Quantization variants are pulled live from Hugging Face. Search to add any GGUF model.
        </p>
        <div ref={searchBoxRef} style={styles.hfSearchBox}>
          <div style={styles.hfSearchRow}>
            <input
              style={styles.hfInput}
              placeholder="Search Hugging Face for a model (e.g. qwen2.5, phi-4, gemma)…"
              value={hfQuery}
              onChange={(e) => setHfQuery(e.target.value)}
              onFocus={() => { if (hfSearched || hfBusy === "search") setShowResults(true); }}
              onKeyDown={(e) => { if (e.key === "Enter") searchHF(); }}
            />
            <button className="btn btn-primary" onClick={searchHF} disabled={hfBusy === "search"}>
              {hfBusy === "search" ? "Searching…" : "🔍 Search HF"}
            </button>
          </div>

          {showResults && (
            <div style={styles.hfDropdown} className="glass-panel">
              {hfBusy === "search" ? (
                <div style={styles.hfLoadingRow}>
                  <span className="spinner" style={styles.hfSpinner} />
                  <span>Searching Hugging Face…</span>
                </div>
              ) : hfResults.length > 0 ? (
                <div style={styles.hfResults}>
                  {hfResults.map((r) => (
                    <div key={r.id} style={styles.hfResult}>
                      <div style={styles.hfResultInfo}>
                        <span style={styles.hfResultId}>{r.id}</span>
                        <span style={styles.hfResultMeta}>▼ {r.downloads.toLocaleString()} · ♥ {r.likes.toLocaleString()}</span>
                      </div>
                      <button className="btn btn-secondary" style={styles.hfAddBtn} onClick={() => addHF(r.id)} disabled={hfBusy === r.id}>
                        {hfBusy === r.id ? "Adding…" : "+ Add"}
                      </button>
                    </div>
                  ))}
                </div>
              ) : hfSearched ? (
                <p style={styles.hfEmpty}>No GGUF models found for that search.</p>
              ) : null}
            </div>
          )}
        </div>
      </div>

      {/* Catalog Grid */}
      <div style={styles.contentArea}>
        {loading ? (
          <div style={styles.loaderContainer}>
            <div style={styles.loader} className="spinner"></div>
            <p>Scanning registry...</p>
          </div>
        ) : models.length === 0 ? (
          <p style={styles.emptyState}>No models available in registry.</p>
        ) : (
          <div style={styles.grid}>
            {models.map(m => {
              const selectedQuant = selectedQuants[m.id] || "";
              const activeVariant = m.variants.find(v => v.quantization === selectedQuant);
              // Per-variant fit from the backend (based on the real file size).
              const assessment = activeVariant?.fit_level
                ? {
                    fit_level: activeVariant.fit_level,
                    explanation: activeVariant.fit_explanation,
                    max_context: activeVariant.max_context,
                    recommendations: activeVariant.recommendations,
                  }
                : undefined;
              const download = downloads[m.id];
              const isDownloaded = activeVariant?.is_downloaded || false;
              
              return (
                <div
                  key={m.id}
                  style={{
                    ...styles.card,
                    borderColor: isDownloaded ? "var(--primary)" : "var(--panel-border)"
                  }}
                  className="glass-panel"
                >
                  <div style={styles.cardHeader}>
                    <div style={styles.modelName}>{m.name}</div>
                    <div style={styles.modelMeta}>
                      {m.parameter_count_billions.toFixed(1)}B params | {m.family}
                    </div>
                  </div>

                  <p style={styles.description}>{m.description}</p>

                  {/* Quantization Picker */}
                  <div style={styles.fieldRow}>
                    <span style={styles.fieldLabel}>Quant:</span>
                    <select
                      value={selectedQuant}
                      onChange={(e) => handleQuantChange(m.id, e.target.value)}
                      disabled={download?.status === "downloading"}
                      style={styles.quantSelect}
                    >
                      {m.variants.map(v => (
                        <option key={v.quantization} value={v.quantization}>
                          {v.quantization} ({(v.file_size_bytes / (1024 * 1024 * 1024)).toFixed(2)} GB)
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Fit Advisor Assessment */}
                  {assessment && (
                    <div style={styles.advisorSection}>
                      <div
                        style={{
                          ...styles.fitBadge,
                          ...getBadgeStyle(assessment.fit_level)
                        }}
                      >
                        {getFitText(assessment.fit_level)}
                      </div>
                      <ul style={styles.recommendationsList}>
                        {(assessment.recommendations ?? []).map((rec, idx) => (
                          <li key={idx} style={styles.recItem}>{rec}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Downloads & Actions */}
                  <div style={styles.actionRow}>
                    {download ? (
                      <div style={styles.downloadProgressBlock}>
                        <DownloadProgress stats={download.stats} status={download.status} compact />
                        <button
                          className="btn btn-secondary"
                          style={{ ...styles.actionBtn, marginTop: "8px" }}
                          onClick={() => handleCancelDownload(m.id)}
                        >
                          Cancel
                        </button>
                      </div>
                    ) : isDownloaded ? (
                      <div style={styles.downloadedActions}>
                        <span style={styles.downloadStatusText}>✅ Local Variant</span>
                        <button
                          className="btn btn-secondary"
                          onClick={() => handleDelete(m.id)}
                          style={styles.actionBtn}
                        >
                          Delete
                        </button>
                      </div>
                    ) : (
                      <button
                        className="btn btn-primary"
                        onClick={() => handleDownload(m.id)}
                        disabled={assessment?.fit_level === "does_not_fit"}
                        style={{
                          ...styles.actionBtn,
                          width: "100%",
                          background: assessment?.fit_level === "does_not_fit" ? "rgba(255,255,255,0.05)" : "var(--accent-gradient)"
                        }}
                      >
                        {assessment?.fit_level === "does_not_fit" ? "Needs Pooling (Disabled)" : "Download & Serve"}
                      </button>
                    )}
                  </div>

                </div>
              );
            })}
          </div>
        )}
      </div>

    </div>
  );
};

const styles: { [key: string]: React.CSSProperties } = {
  catalogWrapper: {
    display: "flex",
    flexDirection: "column",
    height: "100vh",
    width: "100%",
    background: "#09090b",
    overflow: "hidden"
  },
  header: {
    padding: "24px 30px",
    borderBottom: "1px solid var(--panel-border)",
    background: "rgba(10, 10, 15, 0.3)"
  },
  headerTitle: {
    fontSize: "22px",
    color: "#fff",
    marginBottom: "6px"
  },
  headerSub: {
    fontSize: "14px",
    color: "#a1a1aa"
  },
  hfSearchBox: { position: "relative" },
  hfSearchRow: { display: "flex", gap: "10px", marginTop: "14px", alignItems: "center" },
  hfInput: { flexGrow: 1, fontSize: "13px" },
  hfDropdown: {
    position: "absolute",
    top: "calc(100% + 6px)",
    left: 0,
    right: 0,
    zIndex: 50,
    padding: "8px",
    borderRadius: "10px",
    border: "1px solid var(--panel-border)",
    background: "rgba(18,18,26,0.98)",
    boxShadow: "0 12px 32px rgba(0,0,0,0.45)",
    maxHeight: "320px",
    overflowY: "auto",
  },
  hfLoadingRow: { display: "flex", alignItems: "center", gap: "10px", padding: "12px", fontSize: "13px", color: "#a1a1aa" },
  hfSpinner: { width: "16px", height: "16px", flexShrink: 0 },
  hfEmpty: { padding: "12px", fontSize: "13px", color: "#71717a", margin: 0 },
  hfResults: { display: "flex", flexDirection: "column", gap: "6px" },
  hfResult: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 12px", background: "rgba(255,255,255,0.02)", border: "1px solid var(--panel-border)", borderRadius: "8px" },
  hfResultInfo: { display: "flex", flexDirection: "column", gap: "2px", minWidth: 0 },
  hfResultId: { fontSize: "13px", color: "#e4e4e7", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" },
  hfResultMeta: { fontSize: "11px", color: "#71717a" },
  hfAddBtn: { fontSize: "12px", padding: "6px 14px", flexShrink: 0 },
  contentArea: {
    flexGrow: 1,
    overflowY: "auto",
    padding: "30px"
  },
  loaderContainer: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    height: "200px",
    color: "#a1a1aa"
  },
  loader: {
    width: "36px",
    height: "36px",
    borderRadius: "50%",
    border: "2px solid rgba(255,255,255,0.05)",
    borderTopColor: "var(--primary)",
    marginBottom: "16px"
  },
  emptyState: {
    textAlign: "center",
    color: "#71717a",
    marginTop: "40px"
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
    gap: "24px"
  },
  card: {
    borderRadius: "12px",
    padding: "24px",
    display: "flex",
    flexDirection: "column",
    minHeight: "380px",
    transition: "border-color 0.15s ease-out"
  },
  cardHeader: {
    marginBottom: "14px"
  },
  modelName: {
    fontSize: "18px",
    fontWeight: "600",
    color: "#fff"
  },
  modelMeta: {
    fontSize: "12px",
    color: "#71717a",
    marginTop: "4px"
  },
  description: {
    fontSize: "13px",
    color: "#a1a1aa",
    lineHeight: "1.5",
    marginBottom: "20px"
  },
  fieldRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: "20px",
    borderTop: "1px solid rgba(255,255,255,0.03)",
    paddingTop: "14px"
  },
  fieldLabel: {
    fontSize: "13px",
    color: "#71717a"
  },
  quantSelect: {
    padding: "6px 10px",
    fontSize: "12px"
  },
  advisorSection: {
    flexGrow: 1,
    background: "rgba(255,255,255,0.02)",
    borderRadius: "8px",
    padding: "12px",
    marginBottom: "20px"
  },
  fitBadge: {
    display: "inline-block",
    padding: "2px 8px",
    borderRadius: "4px",
    fontSize: "11px",
    fontWeight: "600",
    textTransform: "uppercase",
    border: "1px solid transparent",
    marginBottom: "8px"
  },
  recommendationsList: {
    paddingLeft: "16px",
    color: "#a1a1aa",
    fontSize: "12px",
    lineHeight: "1.4"
  },
  recItem: {
    marginBottom: "4px"
  },
  actionRow: {
    marginTop: "auto"
  },
  actionBtn: {
    fontSize: "13px",
    padding: "10px"
  },
  downloadedActions: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    width: "100%"
  },
  downloadStatusText: {
    fontSize: "13px",
    color: "var(--semantic-success)",
    fontWeight: "500"
  },
  downloadProgressBlock: {
    width: "100%"
  },
  downloadHeaders: {
    display: "flex",
    justifyContent: "space-between",
    fontSize: "12px",
    color: "#a1a1aa",
    marginBottom: "6px"
  },
  progressBarBg: {
    width: "100%",
    height: "4px",
    background: "rgba(255,255,255,0.05)",
    borderRadius: "2px",
    overflow: "hidden"
  },
  progressBarFill: {
    height: "100%",
    background: "var(--accent-gradient)",
    borderRadius: "2px"
  }
};
