import React, { useState, useEffect, useRef } from "react";
import { SetupPage } from "./pages/SetupPage";
import { ChatPage } from "./pages/ChatPage";
import { ModelsPage } from "./pages/ModelsPage";
import { PoolPage } from "./pages/PoolPage";
import { ApiAccessPage } from "./pages/ApiAccessPage";
import { SettingsPage, syncBackgroundSetting } from "./pages/SettingsPage";
import { api } from "./api/endpoints";

function App() {
  const [setupCompleted, setSetupCompleted] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<"chat" | "models" | "pool" | "api" | "settings">("chat");
  const [isServerHealthy, setIsServerHealthy] = useState<boolean>(false);
  const [hardwareSummary, setHardwareSummary] = useState<string>("Detecting...");

  // Count consecutive health-poll failures. The backend is single-threaded
  // while generating a large response, so an occasional slow/failed health
  // poll is normal — we only show "disconnected" after several in a row to
  // stop the status dot flapping red mid-generation (or on tab switch).
  const failuresRef = useRef<number>(0);
  const hwLoadedRef = useRef<boolean>(false);
  const FAILURE_THRESHOLD = 3;

  useEffect(() => {
    const completed = localStorage.getItem("localy_setup_completed") === "true";
    setSetupCompleted(completed);
    // Push the persisted background-run preference to the Rust side so the
    // window-close behaviour is correct from the first close.
    syncBackgroundSetting();
  }, []);

  useEffect(() => {
    checkServerHealth();
    const interval = setInterval(checkServerHealth, 5000);
    // Re-check immediately when the user returns to the window/tab, so the
    // status reflects reality without waiting for the next poll tick.
    const onVisible = () => {
      if (document.visibilityState === "visible") checkServerHealth();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
  }, [setupCompleted]);

  const checkServerHealth = async () => {
    try {
      const health = await api.getHealth();
      if (health.status === "ok") {
        failuresRef.current = 0;
        setIsServerHealthy(true);

        // Hardware specs are static — fetch once after the first healthy poll
        // rather than every 5s (the heavy call was contributing to timeouts).
        if (setupCompleted && !hwLoadedRef.current) {
          hwLoadedRef.current = true;
          try {
            const hw = await api.getHardwareReport();
            setHardwareSummary(`${hw.cpu.brand.split("@")[0].trim()} | ${hw.memory.total_gb.toFixed(0)}GB`);
          } catch {
            hwLoadedRef.current = false; // retry on a later poll
          }
        }
      } else {
        registerFailure();
      }
    } catch {
      registerFailure();
    }
  };

  const registerFailure = () => {
    failuresRef.current += 1;
    if (failuresRef.current >= FAILURE_THRESHOLD) {
      setIsServerHealthy(false);
    }
  };

  const handleSetupComplete = () => {
    localStorage.setItem("localy_setup_completed", "true");
    setSetupCompleted(true);
  };

  // If setup not done, redirect to setup wizard
  if (!setupCompleted) {
    return <SetupPage onComplete={handleSetupComplete} />;
  }

  return (
    <div style={styles.appContainer}>
      
      {/* Global Sidebar Dashboard Navigation */}
      <div style={styles.navSidebar} className="glass-panel">
        <div style={styles.logoRow}>
          <span style={styles.logoIcon}>
            <svg width="26" height="26" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
              <defs>
                <linearGradient id="localyBg" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stopColor="#6366f1" />
                  <stop offset="1" stopColor="#4f46e5" />
                </linearGradient>
              </defs>
              <rect x="96" y="96" width="832" height="832" rx="200" fill="url(#localyBg)" />
              <g stroke="#e0e7ff" strokeWidth="46" strokeLinecap="round" fill="none">
                <line x1="360" y1="300" x2="360" y2="660" />
                <line x1="360" y1="660" x2="700" y2="660" />
              </g>
              <g fill="#ffffff">
                <circle cx="360" cy="300" r="70" />
                <circle cx="360" cy="660" r="70" />
                <circle cx="700" cy="660" r="70" />
              </g>
              <g fill="#4ade80">
                <circle cx="360" cy="300" r="30" />
                <circle cx="360" cy="660" r="30" />
                <circle cx="700" cy="660" r="30" />
              </g>
            </svg>
          </span>
          <span style={styles.logoText}>Localy</span>
        </div>

        <div style={styles.menuList}>
          <div
            onClick={() => setActiveTab("chat")}
            style={{
              ...styles.menuItem,
              background: activeTab === "chat" ? "rgba(99, 102, 241, 0.1)" : "transparent",
              color: activeTab === "chat" ? "#fff" : "var(--text-secondary)"
            }}
          >
            <span style={styles.menuIcon}>💬</span> Chat Playground
          </div>

          <div
            onClick={() => setActiveTab("models")}
            style={{
              ...styles.menuItem,
              background: activeTab === "models" ? "rgba(99, 102, 241, 0.1)" : "transparent",
              color: activeTab === "models" ? "#fff" : "var(--text-secondary)"
            }}
          >
            <span style={styles.menuIcon}>📁</span> Model Catalog
          </div>

          <div
            onClick={() => setActiveTab("pool")}
            style={{
              ...styles.menuItem,
              background: activeTab === "pool" ? "rgba(99, 102, 241, 0.1)" : "transparent",
              color: activeTab === "pool" ? "#fff" : "var(--text-secondary)"
            }}
          >
            <span style={styles.menuIcon}>🔗</span> Device Pool
          </div>

          <div
            onClick={() => setActiveTab("api")}
            style={{
              ...styles.menuItem,
              background: activeTab === "api" ? "rgba(99, 102, 241, 0.1)" : "transparent",
              color: activeTab === "api" ? "#fff" : "var(--text-secondary)"
            }}
          >
            <span style={styles.menuIcon}>🔌</span> API Access
          </div>

          <div
            onClick={() => setActiveTab("settings")}
            style={{
              ...styles.menuItem,
              background: activeTab === "settings" ? "rgba(99, 102, 241, 0.1)" : "transparent",
              color: activeTab === "settings" ? "#fff" : "var(--text-secondary)"
            }}
          >
            <span style={styles.menuIcon}>⚙️</span> Settings
          </div>
        </div>

        {/* Bottom Panel Status & Hardware Specs */}
        <div style={styles.bottomStatus} className="glass-panel">
          <div style={styles.statusRow}>
            <span style={{
              ...styles.statusDot,
              background: isServerHealthy ? "var(--semantic-success)" : "var(--semantic-error)",
              boxShadow: isServerHealthy ? "0 0 8px var(--semantic-success)" : "0 0 8px var(--semantic-error)"
            }} />
            <span style={styles.statusText}>
              {isServerHealthy ? "Backend Online" : "Connecting..."}
            </span>
          </div>

          <div style={styles.specsText} title={hardwareSummary}>
            {hardwareSummary}
          </div>
        </div>
      </div>

      {/* Main Pages Container */}
      <div style={styles.pageArea}>
        {activeTab === "chat" && <ChatPage />}
        {activeTab === "models" && <ModelsPage />}
        {activeTab === "pool" && <PoolPage />}
        {activeTab === "api" && <ApiAccessPage />}
        {activeTab === "settings" && <SettingsPage />}
      </div>

    </div>
  );
}

const styles: { [key: string]: React.CSSProperties } = {
  appContainer: {
    display: "flex",
    flexDirection: "row",
    height: "100vh",
    width: "100vw",
    overflow: "hidden",
    background: "#09090b"
  },
  navSidebar: {
    width: "240px",
    height: "100%",
    borderRight: "1px solid var(--panel-border)",
    display: "flex",
    flexDirection: "column",
    padding: "24px 16px",
    background: "rgba(10, 10, 15, 0.55)",
    flexShrink: 0
  },
  logoRow: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    marginBottom: "36px",
    padding: "0 8px"
  },
  logoIcon: {
    display: "flex",
    alignItems: "center",
    filter: "drop-shadow(0 0 8px rgba(99, 102, 241, 0.45))"
  },
  logoText: {
    fontSize: "18px",
    fontWeight: "700",
    color: "#fff",
    letterSpacing: "-0.01em"
  },
  menuList: {
    display: "flex",
    flexDirection: "column",
    gap: "6px",
    flexGrow: 1
  },
  menuItem: {
    display: "flex",
    alignItems: "center",
    gap: "12px",
    padding: "10px 14px",
    borderRadius: "8px",
    cursor: "pointer",
    fontSize: "14px",
    fontWeight: "500",
    transition: "all 0.15s ease-out"
  },
  menuIcon: {
    fontSize: "16px"
  },
  bottomStatus: {
    marginTop: "auto",
    padding: "14px",
    borderRadius: "10px",
    background: "rgba(0,0,0,0.2)",
    border: "1px solid var(--panel-border)"
  },
  statusRow: {
    display: "flex",
    alignItems: "center",
    gap: "8px"
  },
  statusDot: {
    width: "8px",
    height: "8px",
    borderRadius: "50%"
  },
  statusText: {
    fontSize: "12px",
    fontWeight: "500",
    color: "#fff"
  },
  specsText: {
    fontSize: "11px",
    color: "#71717a",
    marginTop: "6px",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis"
  },
  pageArea: {
    flexGrow: 1,
    height: "100%",
    overflow: "hidden"
  }
};

export default App;
