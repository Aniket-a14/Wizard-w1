/**
 * Backend client.
 *
 * The session id is carried in the `X-Session-Id` header on every call and
 * persisted to localStorage, so a page reload rejoins the same server-side
 * session (and therefore the same loaded dataset and sandbox).
 */

import type {
  DataMode,
  DataModeInfo,
  DocumentSummary,
  ModelDownloadState,
  ModelDownloadsResponse,
  ModelListResponse,
  ProvidersResponse,
  ServerConfig,
  SessionInfo,
  UsageTotals,
  WorkspaceFileEntry,
} from "./types"

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000"

const SESSION_STORAGE_KEY = "wizard.session-id"

export function getStoredSessionId(): string | null {
  if (typeof window === "undefined") return null
  return window.localStorage.getItem(SESSION_STORAGE_KEY)
}

export function storeSessionId(id: string): void {
  if (typeof window === "undefined") return
  window.localStorage.setItem(SESSION_STORAGE_KEY, id)
}

export function clearStoredSessionId(): void {
  if (typeof window === "undefined") return
  window.localStorage.removeItem(SESSION_STORAGE_KEY)
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = "ApiError"
  }
}

/** Normalises FastAPI's several error shapes into a readable sentence. */
async function extractError(response: Response): Promise<string> {
  try {
    const body = await response.json()
    const detail = body?.detail
    if (typeof detail === "string") return detail
    if (Array.isArray(detail)) {
      return detail
        .map((item) =>
          typeof item === "string" ? item : (item?.msg ?? JSON.stringify(item)),
        )
        .join("; ")
    }
    if (detail) return JSON.stringify(detail)
  } catch {
    // fall through to the status text
  }
  return response.statusText || `Request failed (${response.status})`
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const sessionId = getStoredSessionId()
  if (sessionId) headers.set("X-Session-Id", sessionId)
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json")
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers })

  // The server may mint a session on any request; adopt whatever it returns.
  const returned = response.headers.get("X-Session-Id")
  if (returned) storeSessionId(returned)

  if (!response.ok) {
    throw new ApiError(await extractError(response), response.status)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  config: () => request<ServerConfig>("/api/config"),

  session: () => request<SessionInfo>("/api/session"),

  createSession: () => request<SessionInfo>("/api/session", { method: "POST" }),

  deleteSession: () => request<{ message: string }>("/api/session", { method: "DELETE" }),

  resetNamespace: () => request<SessionInfo>("/api/session/reset", { method: "POST" }),

  models: (refresh = false, provider?: string) => {
    const query = new URLSearchParams()
    if (refresh) query.set("refresh", "true")
    if (provider) query.set("provider", provider)
    const suffix = query.toString()
    return request<ModelListResponse>(`/api/models${suffix ? `?${suffix}` : ""}`)
  },

  selectModels: (selection: Record<string, string | number | null>) =>
    request<SessionInfo>("/api/models", {
      method: "POST",
      body: JSON.stringify(selection),
    }),

  /**
   * What this session will and will not send anywhere.
   *
   * Switching the mode can clear a role's provider assignment — one the new mode
   * forbids — so callers must re-read the session afterwards rather than assume
   * their local copy is still accurate.
   */
  dataMode: () => request<DataModeInfo>("/api/data-mode"),

  setDataMode: (body: { mode?: DataMode; schema_only?: boolean }) =>
    request<DataModeInfo>("/api/data-mode", { method: "POST", body: JSON.stringify(body) }),

  /** Override the session default for one source; delete to follow it again. */
  setDatasetPolicy: (dataset: string, schemaOnly: boolean) =>
    request<DataModeInfo>(`/api/data-mode/dataset/${encodeURIComponent(dataset)}`, {
      method: "PUT",
      body: JSON.stringify({ schema_only: schemaOnly }),
    }),

  clearDatasetPolicy: (dataset: string) =>
    request<DataModeInfo>(`/api/data-mode/dataset/${encodeURIComponent(dataset)}`, {
      method: "DELETE",
    }),

  providers: () => request<ProvidersResponse>("/api/providers"),

  /** The key is written to local disk by the backend and never read back. */
  setProviderKey: (provider: string, apiKey: string) =>
    request<{ status: string; provider: string; key_hint: string }>(
      `/api/providers/${encodeURIComponent(provider)}/credentials`,
      { method: "PUT", body: JSON.stringify({ api_key: apiKey }) },
    ),

  deleteProviderKey: (provider: string) =>
    request<{ status: string; provider: string }>(
      `/api/providers/${encodeURIComponent(provider)}/credentials`,
      { method: "DELETE" },
    ),

  usage: () => request<UsageTotals>("/api/usage"),

  /**
   * Installing a model without leaving the app.
   *
   * Downloads are polled rather than streamed: a pull runs for minutes and
   * survives a reload, so a socket held open for the duration would be the
   * fragile choice.
   */
  modelDownloads: (provider?: string) =>
    request<ModelDownloadsResponse>(
      `/api/models/downloads${provider ? `?provider=${encodeURIComponent(provider)}` : ""}`,
    ),

  downloadModel: (model: string, provider?: string) =>
    request<ModelDownloadState>("/api/models/download", {
      method: "POST",
      body: JSON.stringify({ model, provider: provider ?? null }),
    }),

  cancelModelDownload: (model: string, provider?: string) =>
    request<{ status: string }>("/api/models/download/cancel", {
      method: "POST",
      body: JSON.stringify({ model, provider: provider ?? null }),
    }),

  deleteModel: (model: string, provider?: string) => {
    const query = new URLSearchParams({ model })
    if (provider) query.set("provider", provider)
    return request<{ status: string; model: string }>(
      `/api/models/installed?${query.toString()}`,
      { method: "DELETE" },
    )
  },

  upload: (file: File, clean = true) => {
    const form = new FormData()
    form.append("file", file)
    return request<{
      message: string
      dataset: SessionInfo["datasets"][number]
      cleaning_result: string
      warnings: string[]
      session_id: string
    }>(`/api/datasets?clean=${clean}`, { method: "POST", body: form })
  },

  datasets: () => request<SessionInfo>("/api/datasets"),

  /**
   * Attaches a reference document — a data dictionary, a rules page, a set of
   * metric definitions. These are not data: the agent retrieves from them
   * during a run rather than having them pasted into every prompt.
   */
  uploadDocument: (file: File) => {
    const form = new FormData()
    form.append("file", file)
    return request<{
      message: string
      document: DocumentSummary
      session_id: string
    }>("/api/documents", { method: "POST", body: form })
  },

  deleteDocument: (name: string) =>
    request<{ message: string }>(`/api/documents/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),

  activateDataset: (name: string) =>
    request<SessionInfo>(`/api/datasets/${encodeURIComponent(name)}/activate`, {
      method: "POST",
    }),

  deleteDataset: (name: string) =>
    request<{ message: string }>(`/api/datasets/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),

  preview: (params: {
    page?: number
    perPage?: number
    sortBy?: string | null
    sortOrder?: "asc" | "desc"
    dataset?: string | null
  }) => {
    const query = new URLSearchParams()
    query.set("page", String(params.page ?? 1))
    query.set("per_page", String(params.perPage ?? 50))
    if (params.sortBy) query.set("sort_by", params.sortBy)
    if (params.sortOrder) query.set("sort_order", params.sortOrder)
    if (params.dataset) query.set("dataset", params.dataset)
    return request<{
      page: number
      per_page: number
      total_rows: number
      total_pages: number
      columns: string[]
      data: Record<string, unknown>[]
    }>(`/api/data/preview?${query.toString()}`)
  },

  workspaceFiles: () => request<{ files: WorkspaceFileEntry[] }>("/api/workspace/files"),

  deleteWorkspaceFile: (path: string) =>
    request<{ message: string }>(`/api/workspace/file/${path}`, { method: "DELETE" }),

  variables: () =>
    request<{ variables: Record<string, unknown>; sandbox_available: boolean }>(
      "/api/sandbox/variables",
    ),

  interrupt: () => request<{ status: string }>("/api/sandbox/interrupt", { method: "POST" }),

  report: (hours = 24) => request<{ report: string; interaction_count: number }>(`/api/report?hours=${hours}`),
}

/** Absolute URL for a file in the current session's workspace. */
export function workspaceFileUrl(path: string, bustCache = false): string {
  const suffix = bustCache ? `?t=${Date.now()}` : ""
  const session = getStoredSessionId()
  const sessionParam = session ? `${bustCache ? "&" : "?"}session=${session}` : ""
  return `${API_BASE_URL}/api/workspace/file/${path}${suffix}${sessionParam}`
}

export function websocketUrl(): string {
  const base = API_BASE_URL.replace(/^http/, "ws")
  const session = getStoredSessionId()
  return `${base}/ws/chat${session ? `?session=${session}` : ""}`
}
