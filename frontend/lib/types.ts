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
  // Investigation frames. The run is a loop, not a pipeline, so "step 3 of 5"
  // no longer describes it — these carry what the agent chose to do and what it
  // learned. A client that ignores them degrades to the frames above.
  | "iteration_start"
  | "action"
  | "observation"
  | "finding"
  | "plan_revised"
  | "assumption"
  | "verification"
  // What the turn cost. Only emitted when a cloud model was involved.
  | "usage"

export type Phase =
  | "idle"
  | "planning"
  | "awaiting_approval"
  | "searching"
  | "deciding"
  | "inspecting"
  | "consulting"
  | "generating"
  | "executing"
  | "correcting"
  | "reflecting"
  | "reviewing"
  | "verifying"
  | "answering"
  | "done"
  | "failed"

/** What the agent can spend an iteration on. */
export type ActionKind = "inspect" | "code" | "consult" | "search" | "reflect" | "answer"

/**
 * `auto` lets the agent choose its own depth; `fast` is a single shot; `deep`
 * forces a full investigation. `planning` is the legacy name for "investigate,
 * but let me approve the plan first".
 */
export type AnalysisMode = "auto" | "fast" | "deep" | "planning"

/** One completed move in the investigation, as the trail renders it. */
export interface TrailEntry {
  id: string
  iteration: number
  kind: ActionKind
  goal: string
  rationale?: string
  /** True when the model's choice could not be read and a default was applied. */
  inferred?: boolean
  observation?: string
  ok?: boolean
  truncated?: boolean
  chars?: number
}

export interface Verification {
  status: "verified" | "mismatch" | "inconclusive"
  detail: string
}

/** How much of the answer traced back to something actually computed. */
export interface Grounding {
  checked: number
  grounded: number
  ungrounded: string[]
  ok: boolean
  ratio: number
}

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
  kind: "plot_html" | "plot_png" | "plot_description" | "script" | "file"
  name?: string
  data?: string
  text?: string
}

export interface ApprovalRequest {
  /** Open rather than a union: a permission category is a row in the backend's
   *  table, and closing this here would mean editing the type to add one. */
  tool: string
  prompt: string
  plan?: string
  query?: string
  /** Present only for a mid-run permission gate. Its presence is the signal that
   *  the run is still alive and waiting, rather than ended pending a new turn. */
  id?: string
  category?: string
  subject?: string
  detail?: string
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

  /** What the agent did, move by move. */
  trail: TrailEntry[]
  iteration?: number
  iterationBudget?: number
  /** Facts the investigation established along the way. */
  findings: string[]
  /** Silent decisions the code made that change what the number means. */
  assumptions: string[]
  verification?: Verification | null
  grounding?: Grounding | null
  /** Which budget tier the run was sized to — compact, balanced or full. */
  tier?: string
  mode?: AnalysisMode
}

/**
 * Provider ids are strings, not a union.
 *
 * The backend keeps one descriptor table (`src/providers.py`) and reports
 * labels, hints and docs links from it, so adding a backend is a row there
 * rather than an edit here plus two hardcoded `Record<ProviderId, string>`
 * maps that had to be kept in step by hand.
 */
export type ProviderId = string

/** What the session has agreed may leave this machine. */
export type DataMode = "local-only" | "cloud-only" | "hybrid"

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
  label: string
  kind: "local" | "cloud"
  base_url: string
  configured: boolean
  local: boolean
  is_default: boolean
  requires_key: boolean
  /** Whether a key exists at all — from the environment or the local store. */
  has_key: boolean
  key_stored: boolean
  /** Masked tail only. The key itself never leaves the backend. */
  key_hint: string
  /** Whether the current data mode permits this provider. */
  allowed: boolean
  hint: string
  docs_url: string
}

export interface ProvidersResponse {
  providers: ProviderInfo[]
  data_mode: DataMode
}

export interface DataModeInfo {
  mode: DataMode
  description: string
  schema_only: boolean
  /** Per-source overrides. A name absent here follows `schema_only`. */
  per_dataset: Record<string, boolean>
  allowed_providers: string[]
  /** What schema-only withholds. Empty when nothing is being sent anywhere. */
  withheld: string[]
  /** Tools this mode switches off entirely, named so the UI can say so up front. */
  disabled_tools: string[]
}

export type PermissionProfile = "auto-approve" | "ask-always" | "custom"
export type PermissionRuling = "allow" | "ask" | "deny"

export interface PermissionCategoryInfo {
  key: string
  label: string
  description: string
  ruling: PermissionRuling
  /** Never resolves to allow from the profile alone — write-back is enabled per
   *  connection, deliberately, not by picking a profile. */
  always_ask: boolean
  /** False while nothing in the running system reaches this gate yet. */
  live: boolean
}

export interface PermissionsInfo {
  profile: PermissionProfile
  description: string
  categories: PermissionCategoryInfo[]
  grants: string[]
}

export interface UsageRecord {
  provider: string
  model: string
  role: string
  calls: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  /** Null for a local model, and for a cloud model whose price is unpublished. */
  cost_usd: number | null
  estimated: boolean
  cloud: boolean
}

export interface UsageTotals {
  records: UsageRecord[]
  calls: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cost_usd: number | null
  any_cloud: boolean
  estimated: boolean
  /** Cloud models the backend could not price, named rather than under-reported. */
  unpriced_models: string[]
  /** True when nothing in this session can incur cost. */
  local_only: boolean
}

export type DownloadStatus =
  | "queued"
  | "downloading"
  | "completed"
  | "failed"
  | "cancelled"

export interface ModelDownloadState {
  provider: string
  model: string
  status: DownloadStatus
  completed_bytes: number
  total_bytes: number
  /**
   * Null while nothing measurable has been reported. LM Studio says nothing at
   * all while it resolves a repo, and a bar pinned at 0% reads as broken where
   * "Resolving" reads as working.
   */
  percent: number | null
  detail: string
  error: string | null
  started_at: number
  finished_at: number | null
}

export interface ProviderDownloadCapability {
  provider: string
  can_download: boolean
  can_delete: boolean
  /** Why not, when either is false. Shown instead of a button that would fail. */
  reason: string
}

export interface ModelDownloadsResponse {
  downloads: ModelDownloadState[]
  capability: ProviderDownloadCapability
}

export interface ModelListResponse {
  provider: string
  models: ModelInfo[]
  suggested: Record<string, string | null>
  selected: Record<string, string | number | null>
  providers: ProviderInfo[]
  error: string | null
}

export interface DocumentSummary {
  name: string
  chars: number
  chunks: number
  source_format: string
  preview: string
}

export interface DatasetSummary {
  name: string
  /** How generated code addresses this table: `tables['<table_key>']`. */
  table_key: string
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
  documents: DocumentSummary[]
  models: Record<string, string | number | null>
  data_mode: DataMode
  data_policy: { schema_only: boolean; per_dataset: Record<string, boolean> }
  usage: UsageTotals
  sandboxed: boolean
  execution_backend: ExecutionBackend
}

/**
 * Where generated code runs. `docker` is a container per session; `local` is a
 * subprocess per session — isolated from the API process, bounded and
 * interruptible, but sharing the user's filesystem; `inprocess` is the last
 * resort with no isolation at all.
 */
export type ExecutionBackend = "docker" | "local" | "inprocess"

/**
 * The server's plan for fitting the configured models into this machine's RAM.
 * Two 7B models want ~14 GB; a 16 GB laptop running a browser and a sandbox does
 * not have that, and the alternative to planning is the OS paging a model
 * between tokens.
 */
export interface MemoryPlan {
  /** True when both models can stay loaded, so neither reloads between steps. */
  co_resident: boolean
  /** What the model server is told, e.g. "30m" when they fit or "30s" when they do not. */
  keep_alive: string
  budget_gb: number
  required_gb: number
  /** False when even one model alone exceeds the budget — expect disk paging. */
  fits: boolean
  reason: string
  models: { name: string; gb: number }[]
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
  /** "provider:<model>", "local:<model>" or "lexical". */
  embeddings_backend: string
  rag_enabled: boolean
  council_enabled: boolean
  requires_api_key: boolean
  /** How the agentic loop is configured. Read-only — these come from the .env. */
  agent_tier: string
  agent_max_iterations: number
  agent_require_approval: boolean
  agent_permission_profile: PermissionProfile
  agent_consent_timeout: number
  agent_verify: boolean
  agent_grounding_check: boolean
  context_docs_enabled: boolean
  supported_document_formats: string[]
  agent_turn_timeout: number

  /**
   * What local inference was actually configured with. Derived from the machine
   * unless pinned in the .env, and getting them wrong is the usual reason a
   * question is slow — so they are shown rather than left in a file.
   */
  llm_num_thread: number
  llm_num_ctx: number
  llm_keep_alive: string
  /**
   * Whether the manager and worker fit in this machine's memory at the same
   * time. When they do not, each is released after it runs — one reload per
   * step, instead of two oversized models paging each other to disk.
   */
  memory_plan: MemoryPlan | null
  /** Settings that will make this install slow, in plain language. Usually empty. */
  performance_notes: string[]

  /** Where generated code runs, and what the server measured about this host. */
  execution_backend: ExecutionBackend
  /** The configured preference — "auto" resolves to one of the above. */
  execution_backend_setting: string
  /** The configured default. A session may hold a different one. */
  data_mode: DataMode
  data_schema_only: boolean
  sandbox_tier: string
  system_profile: string
  host_cores: number
  host_ram_gb: number | null
  sandbox_mem_limit: string
  max_sessions: number
}

export interface WorkspaceFileEntry {
  name: string
  path: string
  size: number
  type: "image" | "plot" | "table" | "text" | "file"
  modified_at: number
}
