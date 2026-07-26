/**
 * Wire types shared with the backend.
 *
 * The backend emits one frame per orchestrator event. Everything the UI renders
 * is derived from these frames as they arrive — nothing is reconstructed after
 * the fact, which is what allows genuine token-by-token rendering.
 */

export type EventType =
  | "session"
  | "status"
  | "step_start"
  | "step_end"
  | "reasoning_delta"
  | "plan_delta"
  | "content_delta"
  | "code"
  | "stdout"
  | "artifact"
  | "approval_required"
  | "warning"
  | "error"
  | "final"
  | "pong"

export type Phase =
  | "idle"
  | "planning"
  | "awaiting_approval"
  | "searching"
  | "generating"
  | "executing"
  | "correcting"
  | "reviewing"
  | "answering"
  | "done"
  | "failed"

export interface ServerEvent {
  type: EventType
  at?: number
  [key: string]: unknown
}

export interface RunStep {
  id: string
  label: string
  kind: "plan" | "code" | "execute" | "review" | "tool"
  status: "running" | "done" | "failed"
  durationMs?: number
}

export interface Artifact {
  kind: "plot_html" | "plot_png" | "plot_description" | "file"
  name?: string
  data?: string
  text?: string
}

export interface ApprovalRequest {
  tool: "execute_plan" | "web_search"
  prompt: string
  plan?: string
  query?: string
}

export interface ChatMessage {
  id: string
  role: "user" | "assistant"
  content: string
  createdAt: number

  /** Streamed reasoning from the manager model, rendered in a collapsible panel. */
  reasoning?: string
  /** The plan, streamed separately from the final answer. */
  plan?: string
  code?: string
  stdout?: string
  steps: RunStep[]
  artifacts: Artifact[]
  warnings: string[]
  downloads: string[]
  approval?: ApprovalRequest | null
  error?: string
  phase?: Phase
  /** Human-readable label for the current phase, e.g. "Running code". */
  statusLabel?: string
  elapsedMs?: number
  /** True while this message is still receiving frames. */
  streaming?: boolean
}

export type ProviderId = "ollama" | "lmstudio" | "openai" | "custom_gateway"

export interface ModelInfo {
  name: string
  size_bytes: number
  family: string
  parameter_size: string
  quantization: string
  capabilities: string[]
  installed: boolean
  provider: string
  context_length: number
  /** LM Studio only: null elsewhere, since no other provider reports load state. */
  loaded: boolean | null
}

export interface ProviderInfo {
  id: ProviderId
  base_url: string
  configured: boolean
  local: boolean
  is_default: boolean
}

export interface ModelListResponse {
  provider: string
  models: ModelInfo[]
  suggested: Record<string, string | null>
  selected: Record<string, string | number | null>
  providers: ProviderInfo[]
  error: string | null
}

export interface DatasetSummary {
  name: string
  rows: number
  columns: string[]
  column_count: number
  source_format: string
  profile: {
    rows?: number
    columns?: number
    memory_bytes?: number
    truncated?: boolean
    original_rows?: number | null
    renamed_columns?: Record<string, string>
    dropped_columns?: string[]
  }
  loaded_at: number
}

export interface SessionInfo {
  session_id: string
  created_at: number
  last_seen: number
  has_data: boolean
  active_dataset: string | null
  datasets: DatasetSummary[]
  models: Record<string, string | number | null>
  sandboxed: boolean
}

export interface ServerConfig {
  app_name: string
  version: string
  plot_format: "png" | "html"
  sandbox_available: boolean
  sandbox_enabled: boolean
  model_provider: string
  supported_formats: string[]
  max_upload_mb: number
  queue_backend: string
  cache_backend: string
  embeddings_semantic: boolean
  rag_enabled: boolean
  council_enabled: boolean
  requires_api_key: boolean
}

export interface WorkspaceFileEntry {
  name: string
  path: string
  size: number
  type: "image" | "plot" | "table" | "text" | "file"
  modified_at: number
}
