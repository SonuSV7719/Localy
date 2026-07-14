import React, { useState, useEffect } from "react";
import { SetupPage } from "./pages/SetupPage";
import { ChatPage } from "./pages/ChatPage";
import { ModelsPage } from "./pages/ModelsPage";
import { PoolPage } from "./pages/PoolPage";
import { api } from "./api/endpoints";

function App() {
  const [setupCompleted, setSetupCompleted] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<"chat" | "models" | "pool">("chat");
  const [isServerHealthy, setIsServerHealthy] = useState<boolean>(false);
  const [hardwareSummary, setHardwareSummary] = useState<string>("Detecting...");

  useEffect(() => {
    // Check if onboarding completed
    const completed = localStorage.getItem("localy_setup_completed") === "true";
    setSetupCompleted(completed);

    // Run health check and fetch specs if setup done
    checkServerHealth();
    
    const interval = setInterval(checkServerHealth, 5000);
    return () => clearInterval(interval);
  }, [setupCompleted]);

  const checkServerHealth = async () => {
    try {
      const health = await api.getHealth();
      setIsServerHealthy(health.status === "ok");
      
      if (setupCompleted) {
        const hw = await api.getHardwareReport();
        setHardwareSummary(`${hw.cpu.brand.split("@")[0].trim()} | ${hw.memory.total_gb.toFixed(0)}GB`);
      }
    } catch {
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
          <span style={styles.logoIcon}>☄️</span>
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
    fontSize: "24px",
    textShadow: "0 0 10px rgba(99, 102, 241, 0.5)"
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
