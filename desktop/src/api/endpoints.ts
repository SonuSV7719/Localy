// API endpoint mappings
import { apiClient, API_BASE_URL } from "./client";
import {
  HardwareReport,
  FitAssessment,
  RegistryModel,
  BenchmarkResult,
  PoolStatus,
  ShardPlan,
  DiscoveredWorker,
  AccessInfo,
} from "./types";

export const api = {
  /**
   * Get basic health status
   */
  async getHealth(): Promise<{ status: string }> {
    return apiClient.get<{ status: string }>("/health");
  },

  /**
   * Get readiness status (active model info, etc.)
   */
  async getReadiness(): Promise<{ status: string; model_loaded: boolean; active_model: string | null }> {
    return apiClient.get<{ status: string; model_loaded: boolean; active_model: string | null }>("/ready");
  },

  /**
   * Get detailed hardware capability report
   */
  async getHardwareReport(): Promise<HardwareReport> {
    return apiClient.get<HardwareReport>("/system/hardware");
  },

  /**
   * Get detailed fit assessment for a model
   */
  async getModelFit(modelId: string, context?: number): Promise<FitAssessment> {
    const query = context ? `?context=${context}` : "";
    return apiClient.get<FitAssessment>(`/system/hardware/fit/${encodeURIComponent(modelId)}${query}`);
  },

  /**
   * Get list of all registered models annotated with download status and fit assessment.
   * Variants are fetched live from Hugging Face (cached).
   */
  async getModels(): Promise<RegistryModel[]> {
    return apiClient.get<RegistryModel[]>("/system/models");
  },

  /** Extract text from a document (PDF/text/code/md) to use as chat context. */
  async extractDocument(
    file: File
  ): Promise<{ filename: string; text: string; chars: number; truncated: boolean; error?: string }> {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${API_BASE_URL}/system/extract`, { method: "POST", body: fd });
    if (!res.ok) throw new Error(`Extraction failed (HTTP ${res.status})`);
    return res.json();
  },

  /**
   * Search Hugging Face for GGUF models to add to the catalog.
   */
  async searchCatalog(query: string): Promise<{ id: string; downloads: number; likes: number }[]> {
    return apiClient.get<{ id: string; downloads: number; likes: number }[]>(
      `/system/catalog/search?q=${encodeURIComponent(query)}`
    );
  },

  /**
   * Add a Hugging Face GGUF repo to the catalog (all its variants become available).
   */
  async addCatalogModel(repoId: string): Promise<{ id?: string; variants?: number; error?: string }> {
    return apiClient.post<{ id?: string; variants?: number; error?: string }>(
      "/system/catalog/add",
      { repo_id: repoId }
    );
  },

  /**
   * Trigger a standardized benchmark run on a model
   */
  async runBenchmark(modelId: string, iterations: number = 3): Promise<BenchmarkResult> {
    return apiClient.post<BenchmarkResult>("/system/benchmark", {
      model: modelId,
      iterations,
    });
  },

  /**
   * Get historical benchmark results
   */
  async getBenchmarkHistory(): Promise<BenchmarkResult[]> {
    return apiClient.get<BenchmarkResult[]>("/system/benchmark/history");
  },

  /**
   * Delete a locally downloaded model variant
   */
  async deleteModel(modelId: string): Promise<{ status: string }> {
    return apiClient.delete<{ status: string }>("/api/delete", {
      name: modelId,
    });
  },

  // --- Background downloads (server-side; survive tab switches) ---

  /** Start (or resume) a background download. Returns immediately. */
  async startDownload(model: string): Promise<any> {
    return apiClient.post<any>("/system/downloads/start", { model });
  },

  /** Progress of all downloads this session. */
  async getDownloads(): Promise<
    { model_id: string; status: string; completed: number; total: number; speed_mbps: number; error?: string | null }[]
  > {
    return apiClient.get("/system/downloads");
  },

  /** Cancel a background download (partial kept for resume). */
  async cancelDownload(model: string): Promise<any> {
    return apiClient.post<any>("/system/downloads/cancel", { model });
  },

  // --- Pooling (Phase 3) ---

  /** Current pool membership + coordinator state. */
  async getPoolStatus(): Promise<PoolStatus> {
    return apiClient.get<PoolStatus>("/pool/status");
  },

  /** Workers advertised on the LAN via mDNS (optionally auto-join). */
  async discoverPool(autoJoin: boolean = false): Promise<DiscoveredWorker[]> {
    return apiClient.get<DiscoveredWorker[]>(`/pool/discover?auto_join=${autoJoin}`);
  },

  /** Add a worker by address. Pass budgetGb from discovery so the planner uses
   *  the worker's REAL memory (otherwise the backend falls back to a guess). */
  async joinPool(host: string, port: number, label: string = "", budgetGb?: number | null): Promise<any> {
    const body: Record<string, unknown> = { host, port, label };
    if (budgetGb && budgetGb > 0) body.budget_mib = Math.round(budgetGb * 1024);
    return apiClient.post<any>("/pool/join", body);
  },

  /** Remove a worker from the pool. */
  async leavePool(nodeId: string): Promise<{ removed: boolean }> {
    return apiClient.post<{ removed: boolean }>("/pool/leave", { node_id: nodeId });
  },

  /** Pool-fit advisor: does this model fit across the current pool?
   *  May fetch model metadata from HF, so allow more than the default timeout. */
  async poolFit(modelId: string): Promise<ShardPlan> {
    return apiClient.get<ShardPlan>(`/pool/fit/${encodeURIComponent(modelId)}`, { timeoutMs: 60000 });
  },

  /** Load a model split across the pool (spawns the coordinator).
   *  This can take minutes (streaming weights to remote workers over WiFi), so
   *  the client timeout is disabled — the backend enforces its own 900s cap. */
  async loadPooled(model: string, ctx: number = 4096): Promise<ShardPlan> {
    return apiClient.post<ShardPlan>("/pool/load", { model, ctx }, { timeoutMs: 0 });
  },

  /** Stop pooled inference. */
  async unloadPooled(): Promise<{ status: string }> {
    return apiClient.post<{ status: string }>("/pool/unload", {}, { timeoutMs: 30000 });
  },

  /** Share THIS device as a worker (start rpc-server + advertise). */
  async startWorker(): Promise<{ running: boolean; address?: string }> {
    return apiClient.post<{ running: boolean; address?: string }>("/pool/worker/start", {}, { timeoutMs: 60000 });
  },

  /** Stop sharing this device. */
  async stopWorker(): Promise<{ running: boolean }> {
    return apiClient.post<{ running: boolean }>("/pool/worker/stop", {});
  },

  // --- API access (keys + internet tunnel) ---

  /** LAN/local URLs, keys, and tunnel status for the API Access panel. */
  async getAccess(): Promise<AccessInfo> {
    return apiClient.get<AccessInfo>("/system/access");
  },

  /** Generate a new API key. The full `key` is returned once — copy it now. */
  async createKey(label: string): Promise<{ id: string; key: string; label: string }> {
    return apiClient.post<{ id: string; key: string; label: string }>("/system/keys", { label });
  },

  /** Revoke an API key by id. */
  async revokeKey(id: string): Promise<{ revoked: boolean }> {
    return apiClient.delete<{ revoked: boolean }>(`/system/keys/${id}`);
  },

  /** Start the Cloudflare internet tunnel; returns the public URL. */
  async startTunnel(): Promise<{ running: boolean; url: string | null }> {
    return apiClient.post<{ running: boolean; url: string | null }>("/system/tunnel/start", {});
  },

  /** Stop the internet tunnel. */
  async stopTunnel(): Promise<{ running: boolean }> {
    return apiClient.post<{ running: boolean }>("/system/tunnel/stop", {});
  },
};
