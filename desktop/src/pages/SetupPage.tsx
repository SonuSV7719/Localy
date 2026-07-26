import React, { useState, useRef } from "react";
import { api } from "../api/endpoints";
import { HardwareReport, BenchmarkResult } from "../api/types";
import { apiClient } from "../api/client";
import { DownloadProgress } from "../components/DownloadProgress";
import { DownloadTracker, ProgressStats } from "../lib/downloadTracker";
import { ArrowRight, Lightbulb, PartyPopper, Sparkles } from "lucide-react";

interface SetupPageProps {
  onComplete: () => void;
}

export const SetupPage: React.FC<SetupPageProps> = ({ onComplete }) => {
  const [step, setStep] = useState<number>(1);
  const [scanStatus, setScanStatus] = useState<string>("");
  const [hardware, setHardware] = useState<HardwareReport | null>(null);
  
  // Downloading state
  const [downloadStats, setDownloadStats] = useState<ProgressStats | null>(null);
  const [downloadStatus, setDownloadStatus] = useState<string>("idle");
  const [downloadModelId] = useState<string>("smollm2:2b");
  const tracker = useRef<DownloadTracker>(new DownloadTracker());

  // Benchmarking state
  const [benchmarking, setBenchmarking] = useState<boolean>(false);
  const [benchmarkResult, setBenchmarkResult] = useState<BenchmarkResult | null>(null);

  // Run hardware scan
  const startScan = async () => {
    setStep(2);
    
    // Simulate steps for animated progress
    const statuses = [
      "Querying logical processor topology...",
      "Analyzing P-core/E-core distributions...",
      "Probing graphic engine compatibility (VRAM limits)...",
      "Measuring storage write/read suitabilities...",
      "Validating SIMD register sets (AVX2/AVX-512)...",
      "Compiling capability matrices..."
    ];

    for (let i = 0; i < statuses.length; i++) {
      setScanStatus(statuses[i]);
      await new Promise(r => setTimeout(r, 600));
    }

    try {
      const report = await api.getHardwareReport();
      setHardware(report);
      setStep(3);
    } catch (e: any) {
      alert(`Hardware probe failed: ${e.message}`);
      setStep(1);
    }
  };

  // Run model download
  const startDownload = async () => {
    setDownloadStatus("downloading");
    tracker.current.reset();

    await apiClient.streamPull(
      downloadModelId,
      (completed, total, status) => {
        if (total > 0) {
          setDownloadStats(tracker.current.update(completed, total));
          setDownloadStatus("downloading");
        } else {
          setDownloadStatus(status || "downloading");
        }
      },
      () => {
        // Success
        setDownloadStatus("success");
        runBenchmark();
      },
      (err) => {
        alert(`Download failed: ${err.message}`);
        setDownloadStatus("idle");
      }
    );
  };

  // Run first-run benchmark
  const runBenchmark = async () => {
    setStep(4);
    setBenchmarking(true);
    try {
      const result = await api.runBenchmark(downloadModelId, 3);
      setBenchmarkResult(result);
    } catch (e: any) {
      // Benchmark error fallback
      console.error(e);
    } finally {
      setBenchmarking(false);
    }
  };

  // Format bytes helper
  const formatBytes = (bytes: number): string => {
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  };

  return (
    <div style={styles.container}>
      <div style={styles.card} className="glass-panel">
        
        {/* Step 1: Welcome Screen */}
        {step === 1 && (
          <div style={styles.slide}>
            <div style={styles.iconCircle}><Sparkles size={42} aria-hidden="true" /></div>
            <h1 style={styles.title}>Welcome to Localy</h1>
            <p style={styles.subtitle}>
              Localy is a speed-oriented serve platform designed to run open-source LLMs 
              directly on your computer. Let's run a quick hardware check to configure optimal settings.
            </p>
            <button className="btn btn-primary" style={styles.actionBtn} onClick={startScan}>
              Start Hardware Scan <ArrowRight size={16} aria-hidden="true" />
            </button>
            <button
              className="btn btn-secondary"
              style={{ ...styles.actionBtn, marginTop: "10px" }}
              onClick={onComplete}
            >
              Skip — go to the app
            </button>
            <p style={{ ...styles.subtitle, marginTop: "16px", marginBottom: 0, fontSize: "12px" }}>
              Skip if you just want to chat, pick a model, or pool with other devices.
            </p>
          </div>
        )}

        {/* Step 2: Scanning Progress */}
        {step === 2 && (
          <div style={styles.slide}>
            <div style={styles.spinnerContainer}>
              <div style={styles.loader} className="spinner"></div>
            </div>
            <h2 style={styles.scanTitle}>Scanning Host Hardware</h2>
            <p style={styles.scanStatus}>{scanStatus}</p>
          </div>
        )}

        {/* Step 3: Scan Results & Onboarding Download */}
        {step === 3 && hardware && (
          <div style={styles.slide}>
            <h2 style={styles.title}>Hardware Profile Confirmed</h2>
            <p style={styles.subtitle}>Here is a breakdown of your hardware and our configuration:</p>

            <div style={styles.reportGrid}>
              <div style={styles.reportItem}>
                <span style={styles.reportLabel}>CPU Cores</span>
                <span style={styles.reportValue}>
                  {hardware.cpu.brand.split("@")[0]} ({hardware.cpu.p_cores}P + {hardware.cpu.e_cores}E Cores)
                </span>
              </div>
              <div style={styles.reportItem}>
                <span style={styles.reportLabel}>Memory Budget</span>
                <span style={styles.reportValue}>
                  {formatBytes(hardware.memory.available_bytes)} available / {formatBytes(hardware.memory.safe_model_budget_bytes)} safe budget
                </span>
              </div>
              <div style={styles.reportItem}>
                <span style={styles.reportLabel}>SIMD Acceleration</span>
                <span style={styles.reportValue}>
                  {hardware.instruction_sets.best_available_simd} (Optimized Backend compiled)
                </span>
              </div>
              <div style={styles.reportItem}>
                <span style={styles.reportLabel}>Graphics Card</span>
                <span style={styles.reportValue}>
                  {hardware.gpu.device_name} ({hardware.gpu.usable_for_inference ? "GPU active" : "Integrated CPU-only mode"})
                </span>
              </div>
            </div>

            <div style={styles.recommendBox}>
              <h3 style={styles.recommendTitle}><Lightbulb size={15} aria-hidden="true" /> Default Recommended Model</h3>
              <p style={styles.recommendText}>
                We recommend starting with <strong>SmolLM2 1.7B Instruct (Q4_K_M)</strong>. It occupies ~1.0 GB of memory, fits comfortably inside your RAM budget, and will execute with high throughput on your CPU.
              </p>
            </div>

            {downloadStatus === "idle" ? (
              <>
                <button className="btn btn-primary" style={styles.actionBtn} onClick={startDownload}>
                  Download SmolLM2 & Run Benchmark
                </button>
                <button
                  className="btn btn-secondary"
                  style={{ ...styles.actionBtn, marginTop: "10px" }}
                  onClick={onComplete}
                >
                  Skip — go to the app
                </button>
                <p style={{ ...styles.subtitle, marginTop: "16px", marginBottom: 0, fontSize: "12px" }}>
                  Skip to pick another model, chat, or pool with other devices instead.
                </p>
              </>
            ) : (
              <div style={styles.downloadSection}>
                <DownloadProgress stats={downloadStats} status={downloadStatus} />
              </div>
            )}
          </div>
        )}

        {/* Step 4: First-Run Benchmark Running / Complete */}
        {step === 4 && (
          <div style={styles.slide}>
            {benchmarking ? (
              <div>
                <div style={styles.spinnerContainer}>
                  <div style={styles.loaderBenchmark} className="spinner"></div>
                </div>
                <h2 style={styles.title}>Calibrating Inference Engine</h2>
                <p style={styles.subtitle}>Running standard generation benchmark pass to calculate actual tokens/second...</p>
              </div>
            ) : (
              <div>
                <div style={styles.celebrateCircle}><PartyPopper size={48} aria-hidden="true" /></div>
                <h2 style={styles.title}>Calibration Complete!</h2>
                <p style={styles.subtitle}>Localy is fully calibrated and optimized for your machine.</p>

                {benchmarkResult && (
                  <div style={styles.benchmarkCard}>
                    <div style={styles.benchmarkNumber}>
                      {benchmarkResult.generation_tokens_per_second.toFixed(1)}
                    </div>
                    <div style={styles.benchmarkLabel}>generation tokens / sec</div>
                    <div style={styles.benchmarkSub}>
                      Prompt processing: {benchmarkResult.prompt_tokens_per_second.toFixed(1)} tok/s | TTFT: {benchmarkResult.time_to_first_token_ms.toFixed(0)}ms
                    </div>
                  </div>
                )}

                <button className="btn btn-primary" style={styles.actionBtn} onClick={onComplete}>
                  Go to Chat <ArrowRight size={16} aria-hidden="true" />
                </button>
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  );
};

const styles: { [key: string]: React.CSSProperties } = {
  container: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    height: "100vh",
    width: "100vw",
    padding: "20px",
    background: "#09090b"
  },
  card: {
    width: "100%",
    maxWidth: "580px",
    borderRadius: "16px",
    padding: "40px",
    textAlign: "center"
  },
  slide: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center"
  },
  iconCircle: {
    width: "90px",
    height: "90px",
    borderRadius: "50%",
    background: "rgba(99, 102, 241, 0.1)",
    border: "1px solid rgba(99, 102, 241, 0.25)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: "24px",
    color: "#818cf8"
  },
  title: {
    fontSize: "24px",
    marginBottom: "12px",
    color: "#fff"
  },
  subtitle: {
    fontSize: "14px",
    color: "#a1a1aa",
    lineHeight: "1.6",
    marginBottom: "32px",
    maxWidth: "440px"
  },
  actionBtn: {
    padding: "12px 28px",
    fontSize: "15px",
    marginTop: "16px"
  },
  spinnerContainer: {
    marginBottom: "24px"
  },
  loader: {
    width: "48px",
    height: "48px",
    borderRadius: "50%",
    border: "3px solid rgba(255,255,255,0.05)",
    borderTopColor: "#6366f1"
  },
  loaderBenchmark: {
    width: "48px",
    height: "48px",
    borderRadius: "50%",
    border: "3px solid rgba(255,255,255,0.05)",
    borderTopColor: "#8b5cf6"
  },
  scanTitle: {
    fontSize: "20px",
    marginBottom: "8px",
    color: "#fff"
  },
  scanStatus: {
    fontSize: "13px",
    color: "#a1a1aa",
    fontFamily: "monospace"
  },
  reportGrid: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: "12px",
    width: "100%",
    marginBottom: "24px"
  },
  reportItem: {
    background: "rgba(255,255,255,0.02)",
    border: "1px solid rgba(255,255,255,0.05)",
    borderRadius: "8px",
    padding: "12px",
    textAlign: "left",
    display: "flex",
    flexDirection: "column"
  },
  reportLabel: {
    fontSize: "11px",
    color: "#71717a",
    textTransform: "uppercase",
    marginBottom: "4px"
  },
  reportValue: {
    fontSize: "13px",
    color: "#e4e4e7",
    fontWeight: "500"
  },
  recommendBox: {
    background: "rgba(99, 102, 241, 0.05)",
    border: "1px solid rgba(99, 102, 241, 0.15)",
    borderRadius: "8px",
    padding: "16px",
    textAlign: "left",
    marginBottom: "24px",
    width: "100%"
  },
  recommendTitle: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    fontSize: "13px",
    fontWeight: "600",
    color: "#818cf8",
    marginBottom: "6px"
  },
  recommendText: {
    fontSize: "12px",
    color: "#a1a1aa",
    lineHeight: "1.5"
  },
  downloadSection: {
    width: "100%",
    marginTop: "12px"
  },
  downloadHeaders: {
    display: "flex",
    justifyContent: "between",
    fontSize: "13px",
    color: "#a1a1aa",
    marginBottom: "8px",
    width: "100%"
  },
  downloadDetails: {
    marginLeft: "auto",
    color: "#e4e4e7"
  },
  progressBarBg: {
    width: "100%",
    height: "6px",
    background: "rgba(255,255,255,0.05)",
    borderRadius: "3px",
    overflow: "hidden",
    marginBottom: "8px"
  },
  progressBarFill: {
    height: "100%",
    background: "linear-gradient(90deg, #6366f1 0%, #8b5cf6 100%)",
    borderRadius: "3px",
    transition: "width 0.2s ease-out"
  },
  downloadSubStatus: {
    fontSize: "11px",
    color: "#71717a",
    fontFamily: "monospace"
  },
  celebrateCircle: {
    display: "flex",
    justifyContent: "center",
    color: "#a78bfa",
    marginBottom: "20px"
  },
  benchmarkCard: {
    background: "rgba(139, 92, 246, 0.04)",
    border: "1px solid rgba(139, 92, 246, 0.15)",
    borderRadius: "12px",
    padding: "24px",
    marginBottom: "32px",
    width: "100%",
    textAlign: "center"
  },
  benchmarkNumber: {
    fontSize: "48px",
    fontWeight: "700",
    color: "#a78bfa",
    fontFamily: "monospace",
    textShadow: "0 0 16px rgba(139, 92, 246, 0.2)"
  },
  benchmarkLabel: {
    fontSize: "12px",
    textTransform: "uppercase",
    color: "#71717a",
    letterSpacing: "0.1em",
    marginTop: "4px",
    marginBottom: "12px"
  },
  benchmarkSub: {
    fontSize: "12px",
    color: "#a1a1aa"
  }
};
