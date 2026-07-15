// API endpoint mappings
import { apiClient } from "./client";
import {
  HardwareReport,
  FitAssessment,
  RegistryModel,
  BenchmarkResult,
  PoolStatus,
  ShardPlan,
  DiscoveredWorker,
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

  // --- Pooling (Phase 3) ---

  /** Current pool membership + coordinator state. */
  async getPoolStatus(): Promise<PoolStatus> {
    return apiClient.get<PoolStatus>("/pool/status");
  },

  /** Workers advertised on the LAN via mDNS (optionally auto-join). */
  async discoverPool(autoJoin: boolean = false): Promise<DiscoveredWorker[]> {
    return apiClient.get<DiscoveredWorker[]>(`/pool/discover?auto_join=${autoJoin}`);
  },

  /** Manually add a worker by address. */
  async joinPool(host: string, port: number, label: string = ""): Promise<any> {
    return apiClient.post<any>("/pool/join", { host, port, label });
  },

  /** Remove a worker from the pool. */
  async leavePool(nodeId: string): Promise<{ removed: boolean }> {
    return apiClient.post<{ removed: boolean }>("/pool/leave", { node_id: nodeId });
  },

  /** Pool-fit advisor: does this model fit across the current pool? */
  async poolFit(modelId: string): Promise<ShardPlan> {
    return apiClient.get<ShardPlan>(`/pool/fit/${encodeURIComponent(modelId)}`);
  },

  /** Load a model split across the pool (spawns the coordinator). */
  async loadPooled(model: string, ctx: number = 4096): Promise<ShardPlan> {
    return apiClient.post<ShardPlan>("/pool/load", { model, ctx });
  },

  /** Stop pooled inference. */
  async unloadPooled(): Promise<{ status: string }> {
    return apiClient.post<{ status: string }>("/pool/unload", {});
  },

  /** Share THIS device as a worker (start rpc-server + advertise). */
  async startWorker(): Promise<{ running: boolean; address?: string }> {
    return apiClient.post<{ running: boolean; address?: string }>("/pool/worker/start", {});
  },

  /** Stop sharing this device. */
  async stopWorker(): Promise<{ running: boolean }> {
    return apiClient.post<{ running: boolean }>("/pool/worker/stop", {});
  },
};
