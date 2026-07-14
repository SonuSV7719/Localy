import React, { useState, useEffect, useRef } from "react";
import { api } from "../api/endpoints";
import { apiClient } from "../api/client";
import { RegistryModel, FitAssessment } from "../api/types";
import { DownloadProgress } from "../components/DownloadProgress";
import { DownloadTracker, ProgressStats } from "../lib/downloadTracker";

export const ModelsPage: React.FC = () => {
  const [models, setModels] = useState<RegistryModel[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  
  // Track currently selected variant per model by model ID
  // e.g. { "smollm2:2b": "Q4_K_M" }
  const [selectedQuants, setSelectedQuants] = useState<{ [modelId: string]: string }>({});

  // Dynamic Fit Assessments per model ID + Quant
  // e.g. { "smollm2:2b-Q4_K_M": FitAssessment }
  const [fitAssessments, setFitAssessments] = useState<{ [key: string]: FitAssessment }>({});

  // Download status state: smoothed stats + status per model id.
  const [downloads, setDownloads] = useState<{
    [modelId: string]: { stats: ProgressStats | null; status: string };
  }>({});
  const trackers = useRef<{ [modelId: string]: DownloadTracker }>({});

  useEffect(() => {
    fetchCatalog();
  }, []);

  // Fetch complete catalog of models
  const fetchCatalog = async () => {
    setLoading(true);
    try {
      const data = await api.getModels();
      setModels(data);

      // Initialize selected quants and pre-fetch assessments
      const quants: { [modelId: string]: string } = {};
      const assessments: { [key: string]: FitAssessment } = {};

      for (const m of data) {
        if (m.variants.length > 0) {
          // Select downloaded variant first, or default to first variant
          const downloadedVar = m.variants.find(v => v.is_downloaded);
          const defaultQuant = downloadedVar ? downloadedVar.quantization : m.variants[0].quantization;
          quants[m.id] = defaultQuant;

          // Fetch fit assessment
          try {
            const fit = await api.getModelFit(m.id);
            assessments[`${m.id}-${defaultQuant}`] = fit;
          } catch (e) {
            console.error(e);
          }
        }
      }

      setSelectedQuants(quants);
      setFitAssessments(assessments);
    } catch (e) {
      console.error("Failed to fetch model catalog:", e);
    } finally {
      setLoading(false);
    }
  };

  // Handle dropdown quant changes
  const handleQuantChange = async (modelId: string, quant: string) => {
    setSelectedQuants({ ...selectedQuants, [modelId]: quant });

    const key = `${modelId}-${quant}`;
    if (!fitAssessments[key]) {
      try {
        // Run a dynamic check
        const fit = await api.getModelFit(modelId);
        setFitAssessments({ ...fitAssessments, [key]: fit });
      } catch (e) {
        console.error(e);
      }
    }
  };

  // Perform model download with full streaming analytics.
  const handleDownload = async (modelId: string) => {
    const quant = selectedQuants[modelId];
    if (!quant) return;

    const tracker = new DownloadTracker();
    trackers.current[modelId] = tracker;
    setDownloads((prev) => ({ ...prev, [modelId]: { stats: null, status: "downloading" } }));

    await apiClient.streamPull(
      modelId,
      (completed, total, status) => {
        if (total > 0) {
          const stats = tracker.update(completed, total);
          setDownloads((prev) => ({ ...prev, [modelId]: { stats, status: "downloading" } }));
        } else {
          setDownloads((prev) => ({
            ...prev,
            [modelId]: { stats: prev[modelId]?.stats ?? null, status: status || "downloading" },
          }));
        }
      },
      () => {
        setDownloads((prev) => {
          const next = { ...prev };
          delete next[modelId];
          return next;
        });
        delete trackers.current[modelId];
        fetchCatalog();
      },
      (err) => {
        alert(`Download failed: ${err.message}`);
        setDownloads((prev) => {
          const next = { ...prev };
          delete next[modelId];
          return next;
        });
        delete trackers.current[modelId];
      }
    );
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
        <h1 style={styles.headerTitle}>Model Registry Catalog</h1>
        <p style={styles.headerSub}>
          Browse available models. Localy dynamically runs live hardware fit assessments before letting you pull weights.
        </p>
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
              const key = `${m.id}-${selectedQuant}`;
              const assessment = fitAssessments[key];
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
                        {assessment.recommendations.map((rec, idx) => (
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
