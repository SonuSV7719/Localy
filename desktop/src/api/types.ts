// API TypeScript Type Definitions

export interface CPUInfo {
  brand: string;
  architecture: string;
  logical_cores: number;
  physical_cores: number;
  p_cores: number;
  e_cores: number;
  is_hybrid: boolean;
  recommended_generation_threads: number;
  recommended_batch_threads: number;
}

export interface GPUInfo {
  device_name: string;
  vram_total_mb: number;
  usable_for_inference: boolean;
  backend: string;
}

export interface MemoryInfo {
  total_bytes: number;
  available_bytes: number;
  used_bytes: number;
  percent_used: number;
  swap_total_bytes: number;
  swap_used_bytes: number;
  os_overhead_bytes: number;
  safe_model_budget_bytes: number;
  total_gb: number;
  available_gb: number;
  safe_model_budget_gb: number;
  has_swap_pressure: boolean;
  swap_free_bytes: number;
}

export interface StorageInfo {
  path: string;
  total_bytes: number;
  free_bytes: number;
  used_bytes: number;
  percent_used: number;
  read_speed_mbps: number;
  is_ssd: boolean;
  mmap_recommended: boolean;
  free_gb: number;
  total_gb: number;
}

export interface InstructionSetReport {
  avx2: boolean;
  best_available_simd: string;
  sse4_2: boolean;
  is_optimized: boolean;
}

export interface HardwareReport {
  hardware_hash: string;
  cpu: CPUInfo;
  gpu: GPUInfo;
  memory: MemoryInfo;
  storage: StorageInfo;
  instruction_sets: InstructionSetReport;
  timestamp: number;
  summary: string;
}

export interface FitAssessment {
  model_id: string;
  fit_level: "fits_well" | "fits_tight" | "does_not_fit";
  required_memory_bytes: number;
  safe_budget_bytes: number;
  recommendations: string[];
}

export interface RegistryVariant {
  quantization: string;
  file_size_bytes: number;
  sha256: string;
  download_url: string;
  is_downloaded: boolean;
}

export interface RegistryModel {
  id: string;
  name: string;
  family: string;
  parameter_count_billions: number;
  description: string;
  variants: RegistryVariant[];
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface ChatCompletionRequest {
  model: string;
  messages: ChatMessage[];
  temperature?: number;
  top_p?: number;
  max_tokens?: number;
  stream?: boolean;
}

export interface ChatCompletionChoice {
  index: number;
  message: {
    role: string;
    content: string;
  };
  finish_reason: string | null;
}

export interface ChatCompletionResponse {
  id: string;
  object: string;
  created: number;
  model: string;
  choices: ChatCompletionChoice[];
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

export interface BenchmarkResult {
  model_id: string;
  prompt_tokens_per_second: number;
  generation_tokens_per_second: number;
  time_to_first_token_ms: number;
  iterations_run: number;
  hardware_hash: string;
}

// --- Pooling (Phase 3) ---

export interface PoolNode {
  node_id: string;
  address: string;
  is_local: boolean;
  label: string;
  budget_gb: number;
}

export interface PoolLoadProgress {
  active: boolean;
  phase: string; // idle | starting | loading | ready | error | stopped
  stage: string | null; // granular human label (e.g. "Loading tensors")
  ready: boolean;
  error: string | null;
  model: string | null;
  elapsed_s: number;
  eta_s: number | null;
  percent: number | null; // 0..100 if the loader reports it
  bytes_total: number | null;
  bytes_sent: number | null;
  node_count: number;
  remote_count: number;
  last_log: string | null;
}

export interface PoolStatus {
  pooled_active: boolean;
  active_model: string | null;
  proxy_url: string | null;
  worker_running: boolean;
  node_count: number;
  remote_count: number;
  total_budget_gb: number;
  loading?: PoolLoadProgress | null;
  nodes: PoolNode[];
}

export interface ShardPlanNode {
  node_id: string;
  address: string;
  is_local: boolean;
  label: string;
  budget_gb: number;
  layer_share_pct: number;
}

export interface ShardPlan {
  fits: boolean;
  model_size_bytes: number;
  required_bytes: number;
  total_budget_bytes: number;
  total_budget_gb: number;
  tensor_split: number[];
  reason: string;
  recommendations: string[];
  nodes: ShardPlanNode[];
}

export interface DiscoveredWorker {
  node_id: string;
  host: string;
  port: number;
  label: string;
  budget_gb: number | null;
}

// --- API access ---

export interface ApiKeyMasked {
  id: string;
  label: string;
  created: number;
  masked: string;
}

export interface AccessInfo {
  lan_url: string;
  local_url: string;
  port: number;
  keys: ApiKeyMasked[];
  tunnel: { running: boolean; url: string | null };
}
