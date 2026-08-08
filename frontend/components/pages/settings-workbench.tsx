"use client"

import { AlertTriangle, Loader2, RotateCcw, ShieldAlert, ShieldCheck, Volume2, VolumeX } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { PageHeader, Section } from "@/components/page-header"
import { api, clearStoredSessionId, getStoredSessionId } from "@/lib/api"
import type {
  DataModeInfo,
  ModelListResponse,
  PermissionProfile,
  PermissionRuling,
  PermissionsInfo,
  SandboxSelfTest,
  ServerConfig,
  SessionInfo,
  UsageTotals,
} from "@/lib/types"
import { useSound } from "@/lib/use-sound"
import { cn } from "@/lib/utils"

/**
 * Session controls, interface preferences and a straight readout of what the
 * server actually resolved at boot.
 *
 * The diagnostics half is deliberately plain: when someone asks "why is this
 * slow" or "is my data really staying local", the answer should be one screen
 * of facts rather than a support conversation.
 */
export function SettingsWorkbench() {
  const [config, setConfig] = useState<ServerConfig | null>(null)
  const [session, setSession] = useState<SessionInfo | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [dataMode, setDataMode] = useState<DataModeInfo | null>(null)
  const [permissions, setPermissions] = useState<PermissionsInfo | null>(null)
  const [usage, setUsage] = useState<UsageTotals | null>(null)
  const [models, setModels] = useState<ModelListResponse | null>(null)
  const { soundOn, toggleSound } = useSound()

  const refresh = useCallback(async () => {
    const [nextConfig, nextSession, nextMode, nextPermissions, nextUsage, nextModels] = await Promise.allSettled([
      api.config(),
      api.session(),
      api.dataMode(),
      api.permissions(),
      api.usage(),
      api.models(),
    ])
    if (nextConfig.status === "fulfilled") setConfig(nextConfig.value)
    if (nextSession.status === "fulfilled") setSession(nextSession.value)
    if (nextMode.status === "fulfilled") setDataMode(nextMode.value)
    if (nextPermissions.status === "fulfilled") setPermissions(nextPermissions.value)
    if (nextUsage.status === "fulfilled") setUsage(nextUsage.value)
    if (nextModels.status === "fulfilled") setModels(nextModels.value)
    setSessionId(getStoredSessionId())
  }, [])

  const unifyModels = useCallback(async (model: string, provider: string) => {
    setBusy(`unify:${model}`)
    try {
      await api.selectModels({
        manager: model,
        manager_provider: provider,
        worker: model,
        worker_provider: provider,
      })
      const [nextModels, nextConfig] = await Promise.allSettled([api.models(), api.config()])
      if (nextModels.status === "fulfilled") setModels(nextModels.value)
      if (nextConfig.status === "fulfilled") setConfig(nextConfig.value)
    } finally {
      setBusy(null)
    }
  }, [])

  const setSchemaOnly = useCallback(async (schemaOnly: boolean) => {
    setDataMode(await api.setDataMode({ schema_only: schemaOnly }))
  }, [])

  const setProfile = useCallback(async (profile: PermissionProfile) => {
    setPermissions(await api.setPermissions({ profile }))
  }, [])

  const setRuling = useCallback(async (key: string, ruling: PermissionRuling) => {
    // Sent one row at a time. The server owns the matrix, so echoing the whole
    // thing back would let a stale local copy overwrite a row it never touched.
    setPermissions(await api.setPermissions({ categories: { [key]: ruling } }))
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const resetWorkspace = useCallback(async () => {
    setBusy("reset")
    try {
      await api.resetNamespace()
      await refresh()
    } finally {
      setBusy(null)
    }
  }, [refresh])

  const newSession = useCallback(async () => {
    setBusy("session")
    try {
      await api.deleteSession()
    } catch {
      // Already gone; a fresh id is minted on the next call either way.
    } finally {
      clearStoredSessionId()
      await refresh()
      setBusy(null)
    }
  }, [refresh])

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <PageHeader
        eyebrow="Preferences"
        title="Settings"
        description="How this session behaves, and what the server resolved when it started."
      />

      <Section
        title="Interface"
        description="Stored in this browser only. Nothing here is sent to the server."
      >
        <div className="flex items-center justify-between gap-4 rounded-xl border border-border bg-card p-4 shadow-xs">
          <div className="flex min-w-0 items-start gap-3">
            {soundOn ? (
              <Volume2 className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
            ) : (
              <VolumeX className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            )}
            <div className="min-w-0">
              <p className="text-[13.5px] font-medium">Interface sounds</p>
              <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">
                A short chime on load and a click when you send. Off is remembered.
              </p>
            </div>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={soundOn}
            aria-label="Interface sounds"
            onClick={toggleSound}
            className={cn(
              "relative h-6 w-11 shrink-0 rounded-full transition-colors duration-[var(--duration-base)]",
              soundOn ? "bg-brand" : "bg-muted",
            )}
          >
            <span
              className={cn(
                "absolute top-0.5 h-5 w-5 rounded-full bg-card shadow-sm",
                "transition-transform duration-[var(--duration-base)] ease-[var(--ease-out-expo)]",
                soundOn ? "translate-x-[1.375rem]" : "translate-x-0.5",
              )}
            />
          </button>
        </div>
      </Section>

      <Section
        title="Session"
        description="Datasets, chat history and the sandbox container are all scoped to this id."
        actions={
          <>
            <button
              type="button"
              onClick={() => void resetWorkspace()}
              disabled={busy !== null}
              className="flex h-9 items-center gap-2 rounded-lg border border-border bg-card px-3.5 text-[13px] font-medium shadow-xs transition-colors duration-[var(--duration-fast)] hover:border-brand/40 disabled:opacity-50"
            >
              {busy === "reset" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RotateCcw className="h-3.5 w-3.5" />
              )}
              Clear variables
            </button>
            <button
              type="button"
              onClick={() => void newSession()}
              disabled={busy !== null}
              className="flex h-9 items-center gap-2 rounded-lg border border-destructive/30 px-3.5 text-[13px] font-medium text-destructive transition-colors duration-[var(--duration-fast)] hover:bg-destructive/8 disabled:opacity-50"
            >
              {busy === "session" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              Start over
            </button>
          </>
        }
      >
        <dl className="grid gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-3">
          <Fact label="Session id" value={sessionId ? `${sessionId.slice(0, 12)}…` : "Not yet issued"} mono />
          <Fact label="Datasets loaded" value={String(session?.datasets.length ?? 0)} />
          <Fact label="Active dataset" value={session?.active_dataset ?? "None"} />
        </dl>
        <p className="mt-3 text-[12px] leading-relaxed text-muted-foreground">
          <strong className="font-medium text-foreground">Clear variables</strong> resets the sandbox
          namespace but keeps your data loaded.{" "}
          <strong className="font-medium text-foreground">Start over</strong> discards the session
          entirely — datasets, history and container.
        </p>
      </Section>

      <Section
        title="Data"
        description="Which models this session may reach, and how much of your data a cloud-bound prompt carries."
      >
        <div className="rounded-xl border border-border bg-card p-4 shadow-xs">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="text-[13.5px] font-medium">{MODE_LABELS[dataMode?.mode ?? ""] ?? "—"}</span>
            <span className="text-[12.5px] text-muted-foreground">{dataMode?.description}</span>
          </div>
          <p className="mt-2 text-[12px] text-muted-foreground">
            Change it from the control in the sidebar — it is there on every screen because it decides
            whether anything leaves this machine.
          </p>

          {/* Named up front rather than discovered mid-run: a tool this mode
              switches off is unavailable, not merely unchosen. */}
          {dataMode && dataMode.disabled_tools.length > 0 && (
            <p className="mt-3 border-t border-border pt-3 text-[12.5px] leading-relaxed text-muted-foreground">
              Unavailable in this mode:{" "}
              <span className="font-medium text-foreground">
                {dataMode.disabled_tools.map((tool) => tool.replace(/_/g, " ")).join(", ")}
              </span>
              . The agent is not permitted to use it, rather than being asked not to.
            </p>
          )}
        </div>

        {/* Only meaningful once something can be cloud-bound. Under local-only
            nothing is withheld because nothing is sent. */}
        {dataMode && dataMode.mode !== "local-only" && (
          <div className="mt-3 rounded-xl border border-border bg-card p-4 shadow-xs">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-[13.5px] font-medium">Withhold real values from cloud prompts</p>
                <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">
                  Column names, types, null rates and row counts still go — a model cannot write
                  correct code without them. Computed results still come back, because the answer is
                  written from them.
                </p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={dataMode.schema_only}
                aria-label="Withhold real values from cloud prompts"
                onClick={() => void setSchemaOnly(!dataMode.schema_only)}
                className={cn(
                  "relative h-6 w-11 shrink-0 rounded-full transition-colors duration-[var(--duration-base)]",
                  dataMode.schema_only ? "bg-brand" : "bg-muted",
                )}
              >
                <span
                  className={cn(
                    "absolute top-0.5 h-5 w-5 rounded-full bg-card shadow-sm",
                    "transition-transform duration-[var(--duration-base)] ease-[var(--ease-out-expo)]",
                    dataMode.schema_only ? "translate-x-[1.375rem]" : "translate-x-0.5",
                  )}
                />
              </button>
            </div>

            {dataMode.withheld.length > 0 && (
              <ul className="mt-3 space-y-1 border-t border-border pt-3">
                {dataMode.withheld.map((item) => (
                  <li key={item} className="text-[12px] text-muted-foreground">
                    — {item}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="mt-3">
          <UsagePanel usage={usage} />
        </div>
      </Section>

      <Section
        title="Permissions"
        description="What the agent may do without asking. Separate from the data mode above: that decides what is possible at all, this decides what you are asked about."
      >
        <PermissionsPanel
          permissions={permissions}
          onProfileChange={setProfile}
          onRulingChange={setRuling}
        />
      </Section>

      <Section
        title="Execution"
        description="Where generated code runs. Docker is opt-in — set EXECUTION_BACKEND in backend/.env."
      >
        <dl className="grid gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-3">
          <Fact
            label="Runtime"
            value={config ? BACKEND_LABELS[config.execution_backend] ?? config.execution_backend : "—"}
            tone={config ? BACKEND_TONE[config.execution_backend] : undefined}
          />
          <Fact
            label="Setting"
            value={
              config
                ? config.execution_backend_setting === config.execution_backend
                  ? config.execution_backend_setting
                  : `${config.execution_backend_setting} → ${config.execution_backend}`
                : "—"
            }
            mono
          />
          <Fact
            label="Containment"
            value={
              config
                ? (ISOLATION_LABELS[config.execution_isolation] ?? config.execution_isolation)
                : "—"
            }
            tone={config?.execution_isolation === "none" ? "warn" : undefined}
          />
          <Fact
            label="Toolkit tier"
            value={config ? TIER_TOOLKIT_LABELS[config.sandbox_tier] ?? config.sandbox_tier : "—"}
          />
          <Fact label="Memory per runtime" value={config?.sandbox_mem_limit || "—"} mono />
          <Fact label="Concurrent sessions" value={config ? String(config.max_sessions) : "—"} />
          <Fact label="Plot format" value={config?.plot_format ?? "—"} />
        </dl>

        {config && <IsolationNote isolation={config.execution_isolation} />}
        {config && <SandboxPanel config={config} />}
      </Section>

      <Section
        title="This machine"
        description="Measured at boot. Thread count, runtime memory and the session cap are derived from these unless you set them yourself."
      >
        <dl className="grid gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
          <Fact
            label="Profile"
            value={config ? PROFILE_LABELS[config.system_profile] ?? config.system_profile : "—"}
          />
          <Fact label="CPU cores" value={config?.host_cores ? String(config.host_cores) : "—"} />
          <Fact
            label="Memory"
            value={config?.host_ram_gb ? `${config.host_ram_gb} GB` : "—"}
          />
          <Fact
            label="Embeddings"
            value={config ? EMBEDDING_LABEL(config.embeddings_backend) : "—"}
            tone={config ? (config.embeddings_semantic ? "ok" : undefined) : undefined}
          />
        </dl>
        <p className="mt-3 text-[12.5px] leading-relaxed text-muted-foreground">
          Embeddings come from whichever model server you already run — Ollama&apos;s{" "}
          <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11.5px]">/api/embed</code> or
          an OpenAI-compatible{" "}
          <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11.5px]">/v1/embeddings</code>
          . Pull an embedding model to get semantic retrieval; without one, matching falls back to
          word overlap and nothing breaks.
        </p>
      </Section>

      <Section
        title="Inference"
        description="What local inference actually runs with. Derived from the machine above unless you pin them in backend/.env — and a pinned value that does not fit the machine is the usual reason a question is slow."
      >
        <dl className="grid gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-5">
          <Fact
            label="Inference threads"
            value={config?.llm_num_thread ? String(config.llm_num_thread) : "—"}
            tone={config && config.llm_num_thread > config.host_cores ? "warn" : undefined}
          />
          <Fact
            label="Context window"
            value={config?.llm_num_ctx ? config.llm_num_ctx.toLocaleString() : "—"}
            mono
          />
          <Fact
            label="Model kept loaded"
            value={config?.memory_plan?.keep_alive || config?.llm_keep_alive || "—"}
            mono
          />
          <Fact
            label="Turn deadline"
            value={
              config ? (config.agent_turn_timeout > 0 ? `${Math.round(config.agent_turn_timeout)}s` : "None") : "—"
            }
          />
          <Fact
            label="Memory"
            value={
              config?.memory_plan
                ? `${config.memory_plan.required_gb.toFixed(1)} / ${config.memory_plan.budget_gb.toFixed(1)} GB`
                : "—"
            }
            tone={config?.memory_plan ? (config.memory_plan.fits ? undefined : "warn") : undefined}
            mono
          />
        </dl>

        {config?.memory_plan && config.memory_plan.models.length > 0 ? (
          <div className="mt-3 rounded-xl border border-border bg-muted/30 px-3.5 py-3">
            <p className="text-[12.5px] leading-relaxed text-foreground">
              {config.memory_plan.co_resident
                ? "Both models stay in memory between steps, so neither is reloaded from disk."
                : "Each model is released after it runs, so they never compete for memory."}{" "}
              <span className="text-muted-foreground">{config.memory_plan.reason}.</span>
            </p>
            <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted-foreground">
              {config.memory_plan.models.map((model) => (
                <li key={model.name} className="font-mono">
                  {model.name} · {model.gb} GB
                </li>
              ))}
            </ul>

            {!config.memory_plan.co_resident &&
            models?.selected.manager &&
            models?.selected.worker &&
            (models.selected.manager !== models.selected.worker ||
              models.selected.manager_provider !== models.selected.worker_provider) ? (
              <div className="mt-2.5 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() =>
                    void unifyModels(
                      String(models.selected.manager),
                      String(models.selected.manager_provider),
                    )
                  }
                  disabled={busy === `unify:${models.selected.manager}`}
                  className="rounded-lg border border-brand/30 bg-brand-soft px-2.5 py-1.5 text-[12px] font-medium text-brand transition-colors duration-[var(--duration-fast)] hover:brightness-105 disabled:opacity-50"
                >
                  Use {String(models.selected.manager)} for both roles
                </button>
                <button
                  type="button"
                  onClick={() =>
                    void unifyModels(
                      String(models.selected.worker),
                      String(models.selected.worker_provider),
                    )
                  }
                  disabled={busy === `unify:${models.selected.worker}`}
                  className="rounded-lg border border-brand/30 bg-brand-soft px-2.5 py-1.5 text-[12px] font-medium text-brand transition-colors duration-[var(--duration-fast)] hover:brightness-105 disabled:opacity-50"
                >
                  Use {String(models.selected.worker)} for both roles
                </button>
              </div>
            ) : null}
          </div>
        ) : null}

        {config && config.performance_notes.length > 0 ? (
          <ul className="mt-3 space-y-2">
            {config.performance_notes.map((note) => (
              <li
                key={note}
                className="flex gap-2.5 rounded-xl border border-warning/30 bg-warning/5 px-3.5 py-3 text-[12.5px] leading-relaxed text-foreground"
              >
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden />
                <span>{note}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-[12.5px] leading-relaxed text-muted-foreground">
            Nothing here is working against this machine. The manager and worker models alternate every
            step, and how they share memory is decided from the sizes above rather than left to chance.
          </p>
        )}
      </Section>

      <Section
        title="Services"
        description="Optional infrastructure. None of it is required."
      >
        <dl className="grid gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-3">
          <Fact label="Default provider" value={config?.model_provider ?? "—"} />
          <Fact label="Job queue" value={config?.queue_backend ?? "—"} />
          <Fact label="Cache" value={config?.cache_backend ?? "—"} />
          <Fact label="RAG" value={config ? (config.rag_enabled ? "On" : "Off") : "—"} />
          <Fact label="Review council" value={config ? (config.council_enabled ? "On" : "Off") : "—"} />
          <Fact label="Max upload" value={config ? `${config.max_upload_mb} MB` : "—"} />
        </dl>
      </Section>

      <Section
        title="Agent"
        description="How the analysis loop behaves. The agent chooses its next move from real execution output, so these govern how far it is allowed to go and how hard its answer is checked."
      >
        <dl className="grid gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-3">
          <Fact
            label="Depth tier"
            value={config ? TIER_LABELS[config.agent_tier] ?? config.agent_tier : "—"}
          />
          <Fact label="Iteration ceiling" value={config ? String(config.agent_max_iterations) : "—"} />
          <Fact
            label="Plan approval gate"
            value={config ? (config.agent_require_approval ? "Required" : "Off") : "—"}
          />
          <Fact
            label="Consent timeout"
            value={config ? `${Math.round(config.agent_consent_timeout)}s` : "—"}
          />
          <Fact
            label="Verification"
            value={config ? (config.agent_verify ? "Recomputes the result" : "Off") : "—"}
          />
          <Fact
            label="Grounding check"
            value={config ? (config.agent_grounding_check ? "On" : "Off") : "—"}
          />
          <Fact
            label="Reference documents"
            value={config ? (config.context_docs_enabled ? "Accepted" : "Disabled") : "—"}
          />
        </dl>

        <p className="mt-3 text-[12.5px] leading-relaxed text-muted-foreground">
          On <span className="font-medium text-foreground">auto</span>, depth is inferred from the
          reasoning model&apos;s parameter count: under 4B runs a short loop with no reflection or
          verification, 4–30B the default, 30B and above the longest. Hosted models report no size and
          are treated as the middle tier. The approval gate here is about the{" "}
          <span className="font-medium text-foreground">plan</span>; what the agent may do while
          carrying one out is the Permissions section above.
        </p>
      </Section>

      <Section title="Formats" description="Read natively, without conversion.">
        <div className="space-y-3">
          <div>
            <p className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              Data
            </p>
            <div className="flex flex-wrap gap-1.5">
              {(config?.supported_formats ?? []).map((format) => (
                <span
                  key={format}
                  className="rounded-md border border-border bg-card px-2 py-1 font-mono text-[11.5px] text-muted-foreground shadow-xs"
                >
                  .{format}
                </span>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              Reference documents
            </p>
            <div className="flex flex-wrap gap-1.5">
              {(config?.supported_document_formats ?? []).map((format) => (
                <span
                  key={format}
                  className="rounded-md border border-border bg-card px-2 py-1 font-mono text-[11.5px] text-muted-foreground shadow-xs"
                >
                  {format}
                </span>
              ))}
            </div>
          </div>
        </div>
      </Section>
    </div>
  )
}

const MODE_LABELS: Record<string, string> = {
  "local-only": "Local only",
  "cloud-only": "Cloud only",
  hybrid: "Hybrid",
}

const BACKEND_LABELS: Record<string, string> = {
  host: "Host subprocess",
  docker: "Docker container",
  inprocess: "In-process (no isolation)",
}

const BACKEND_TONE: Record<string, "ok" | "warn" | undefined> = {
  host: "ok",
  docker: "ok",
  inprocess: "warn",
}

const ISOLATION_LABELS: Record<string, string> = {
  container: "Container",
  "os-sandbox": "OS sandbox",
  process: "Separate process",
  none: "None",
}

const TIER_TOOLKIT_LABELS: Record<string, string> = {
  core: "Core — pandas, duckdb, charts",
  standard: "Standard — + stats and ML",
  full: "Full — + survival and geospatial",
}

const PROFILE_LABELS: Record<string, string> = {
  laptop: "Laptop",
  server: "Server",
  hpc: "HPC",
}

/** Turns "provider:ollama:nomic-embed-text" into something readable. */
function EMBEDDING_LABEL(backend: string): string {
  if (backend === "lexical") return "Word overlap"
  const model = backend.split(":").slice(-1)[0]
  return backend.startsWith("provider:") ? `${model} (provider)` : `${model} (local)`
}

/**
 * Says what the containment actually is. Keyed on `isolation` rather than on the
 * backend name, because the two stopped being the same question: the host
 * backend's containment depends on what this OS could enforce, and only the
 * server knows that. `process` is a supported way to run rather than a failure,
 * so it gets a statement of what it does and does not protect — not a warning.
 */
function IsolationNote({ isolation }: { isolation: string }) {
  if (isolation === "container") {
    return (
      <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-success/25 bg-success/8 p-3.5 text-[13px] leading-relaxed text-success">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
        <span>
          Generated code runs in a container of its own, with capabilities dropped and memory, PID
          and CPU ceilings applied.
        </span>
      </div>
    )
  }

  if (isolation === "process") {
    return (
      <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-border bg-muted/40 p-3.5 text-[13px] leading-relaxed text-muted-foreground">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
        <span>
          Generated code runs in a separate process with its own memory ceiling, a per-step timeout
          and a working Stop button, and it keeps its variables between steps. It is not a security
          boundary: it runs as you, with your files. The static guard still applies. Use Docker for
          data or questions you did not write yourself.
        </span>
      </div>
    )
  }

  return (
    <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-warning/25 bg-warning/8 p-3.5 text-[13px] leading-relaxed text-warning">
      <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
      <span>
        Code runs inside the API process itself, with no isolation and no memory ceiling, and its
        variables do not survive between steps. Set{" "}
        <code className="font-mono text-[11.5px]">EXECUTION_BACKEND=host</code> to run it in a
        separate process instead.
      </span>
    </div>
  )
}

const FEATURE_LABELS: Record<string, string> = {
  filesystem: "Filesystem",
  network: "Outbound network",
  memory: "Memory ceiling",
  processes: "Process count",
}

const SANDBOX_MODE_LABELS: Record<string, string> = {
  off: "Off — no OS policy is applied",
  "best-effort": "Best effort — applies what this OS supports",
  require: "Required — refuses to run uncontained",
}

/**
 * What the OS sandbox enforces, feature by feature, and a button that proves it.
 *
 * The capability list renders from `/api/config` and costs nothing, but it only
 * says what this machine *can* do. The self-test spawns a child that tries to
 * escape and reports what actually stopped it — which is the difference between
 * documented containment and verified containment, and the reason it is a
 * button rather than another row of text.
 */
function SandboxPanel({ config }: { config: ServerConfig }) {
  const [result, setResult] = useState<SandboxSelfTest | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const capability = config.sandbox_capability
  const features = capability?.features ?? []

  const runSelfTest = useCallback(async () => {
    setRunning(true)
    setError(null)
    try {
      setResult(await api.sandboxSelfTest())
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The self-test could not be run")
    } finally {
      setRunning(false)
    }
  }, [])

  if (config.execution_backend !== "host" || !features.length) return null

  return (
    <div className="mt-4 rounded-xl border border-border bg-muted/30 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[13px] font-medium text-foreground">OS sandbox</p>
          <p className="text-[12.5px] text-muted-foreground">
            {SANDBOX_MODE_LABELS[config.host_sandbox] ?? config.host_sandbox} · {capability.mechanism}
          </p>
        </div>
        <button
          type="button"
          onClick={runSelfTest}
          disabled={running || config.host_sandbox === "off"}
          className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-[12.5px] font-medium transition-colors hover:bg-muted disabled:opacity-50"
        >
          {running && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {running ? "Trying to escape…" : "Verify"}
        </button>
      </div>

      <ul className="mt-3 space-y-1.5">
        {features.map((feature) => (
          <li key={feature.key} className="flex items-start gap-2 text-[12.5px] leading-relaxed">
            {feature.supported ? (
              <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />
            ) : (
              <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
            )}
            <span className="text-muted-foreground">
              <span className="font-medium text-foreground">
                {FEATURE_LABELS[feature.key] ?? feature.key}
              </span>{" "}
              — {feature.supported ? "enforced" : "not enforced"}: {feature.detail}
            </span>
          </li>
        ))}
      </ul>

      {error && <p className="mt-3 text-[12.5px] text-warning">{error}</p>}

      {result && (
        <div className="mt-3 border-t border-border pt-3">
          <p className={cn("text-[12.5px] font-medium", result.ok ? "text-success" : "text-warning")}>
            {result.ok ? "Verified" : "Not verified"} — {result.detail}
          </p>
          <ul className="mt-1.5 space-y-1">
            {Object.entries(result.checks).map(([name, check]) => (
              <li key={name} className="text-[12px] leading-relaxed text-muted-foreground">
                <code className="font-mono text-[11.5px] text-foreground">{name}</code>: {check.outcome} —{" "}
                {check.detail}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

/** Plain-English names for the budget tiers the backend reports. */
const TIER_LABELS: Record<string, string> = {
  auto: "Auto — inferred from the model",
  compact: "Compact — short loop for small models",
  balanced: "Balanced",
  full: "Full — longest investigation",
}

function Fact({
  label,
  value,
  mono,
  tone,
}: {
  label: string
  value: string
  mono?: boolean
  tone?: "ok" | "warn"
}) {
  return (
    <div className="bg-card px-4 py-3.5">
      <dt className="font-mono text-[9.5px] uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </dt>
      <dd
        className={cn(
          "mt-1 truncate text-[13px] font-medium",
          mono && "font-mono",
          tone === "ok" && "text-success",
          tone === "warn" && "text-warning",
        )}
      >
        {value}
      </dd>
    </div>
  )
}


const PERMISSION_PROFILE_LABELS: Record<PermissionProfile, string> = {
  "auto-approve": "Auto approve",
  "ask-always": "Ask always",
  custom: "Custom",
}

const RULINGS: PermissionRuling[] = ["allow", "ask", "deny"]

/**
 * The profile, and under `custom` the per-category matrix behind it.
 *
 * Write-back gets its own treatment rather than being one row among equals: it
 * is the only category no blanket profile may cover, and rendering it as an
 * ordinary toggle that silently refuses "allow" would be worse than saying so.
 *
 * The connector categories are shown while nothing reaches them yet, labelled as
 * such. Hiding them would mean a profile set today quietly acquired new meaning
 * when connectors ship; claiming they were live would advertise something that
 * does not exist.
 */
function PermissionsPanel({
  permissions,
  onProfileChange,
  onRulingChange,
}: {
  permissions: PermissionsInfo | null
  onProfileChange: (profile: PermissionProfile) => Promise<void>
  onRulingChange: (key: string, ruling: PermissionRuling) => Promise<void>
}) {
  if (!permissions) {
    return <p className="text-[13px] text-muted-foreground">Loading…</p>
  }

  const custom = permissions.profile === "custom"

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-border bg-card p-4 shadow-xs">
        <div
          className="flex flex-wrap items-center gap-0.5 rounded-lg bg-muted p-0.5"
          role="radiogroup"
          aria-label="Permission profile"
        >
          {(Object.keys(PERMISSION_PROFILE_LABELS) as PermissionProfile[]).map((profile) => (
            <button
              key={profile}
              type="button"
              role="radio"
              aria-checked={permissions.profile === profile}
              onClick={() => void onProfileChange(profile)}
              className={cn(
                "rounded-md px-3 py-1.5 text-[12.5px] font-medium",
                "transition-[background-color,color,box-shadow] duration-[var(--duration-fast)]",
                permissions.profile === profile
                  ? "bg-card text-foreground shadow-xs"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {PERMISSION_PROFILE_LABELS[profile]}
            </button>
          ))}
        </div>
        <p className="mt-3 text-[12.5px] leading-relaxed text-muted-foreground">
          {permissions.description}
        </p>
        <p className="mt-2 text-[12px] leading-relaxed text-muted-foreground/80">
          This is not the plan-approval gate. That one asks before the agent starts; these ask before
          it takes a specific action part-way through.
        </p>
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-card shadow-xs">
        {permissions.categories.map((category) => (
          <div
            key={category.key}
            className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-4 py-3.5 last:border-b-0"
          >
            <div className="min-w-0 flex-1">
              <p className="flex flex-wrap items-center gap-2 text-[13.5px] font-medium">
                {category.label}
                {category.always_ask && (
                  <span className="rounded-full bg-warning/10 px-2 py-0.5 text-[10px] font-medium text-warning">
                    Never auto-approved
                  </span>
                )}
                {!category.live && (
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                    Not reachable yet
                  </span>
                )}
              </p>
              <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">
                {category.description}
                {category.always_ask &&
                  " Enabled per connection, once, deliberately — never by a profile."}
              </p>
            </div>

            <div
              className="flex shrink-0 items-center gap-0.5 rounded-lg bg-muted p-0.5"
              role="radiogroup"
              aria-label={`${category.label} permission`}
            >
              {RULINGS.map((ruling) => {
                // Disabled rather than hidden: the choice exists and is refused
                // for a reason, and a missing button explains nothing.
                const forbidden = category.always_ask && ruling === "allow"
                return (
                  <button
                    key={ruling}
                    type="button"
                    role="radio"
                    aria-checked={category.ruling === ruling}
                    disabled={!custom || forbidden}
                    title={forbidden ? "Write-back is enabled per connection, not by a profile." : undefined}
                    onClick={() => void onRulingChange(category.key, ruling)}
                    className={cn(
                      "rounded-md px-2.5 py-1 text-[11.5px] font-medium capitalize",
                      "transition-[background-color,color,box-shadow] duration-[var(--duration-fast)]",
                      "disabled:cursor-not-allowed disabled:opacity-45",
                      category.ruling === ruling
                        ? "bg-card text-foreground shadow-xs"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {ruling}
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </div>

      {!custom && (
        <p className="text-[12px] text-muted-foreground">
          Switch to Custom to set these individually.
        </p>
      )}

      {permissions.grants.length > 0 && (
        <div className="rounded-xl border border-border bg-card p-4 shadow-xs">
          <p className="text-[13.5px] font-medium">Already approved this session</p>
          <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">
            The agent will not ask again for these until the session ends. Tightening the profile
            clears them.
          </p>
          <ul className="mt-2.5 space-y-1 border-t border-border pt-2.5">
            {permissions.grants.map((grant) => (
              <li key={grant} className="font-mono text-[11.5px] text-muted-foreground">
                {grant}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

/**
 * What this session has spent.
 *
 * Under local-only there is no meter at all — not a zero. A "$0.00" reads as a
 * figure that was computed, and the true statement is that no call could have
 * cost anything. A cloud model whose price is not published is reported in
 * tokens and named, rather than folded into a total that would then be wrong.
 */
function UsagePanel({ usage }: { usage: UsageTotals | null }) {
  if (!usage) return null

  if (usage.local_only) {
    return (
      <div className="rounded-xl border border-success/25 bg-success/5 p-4">
        <p className="text-[13.5px] font-medium text-success">No external calls</p>
        <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">
          Every model in this session runs on this machine, so there is nothing to bill and nothing
          to meter.
        </p>
      </div>
    )
  }

  if (usage.calls === 0) {
    return (
      <div className="rounded-xl border border-border bg-card p-4">
        <p className="text-[13.5px] font-medium">No calls yet</p>
        <p className="mt-1 text-[12.5px] text-muted-foreground">
          Usage appears here once this session asks a question.
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[13.5px] font-medium">
          {usage.calls} call{usage.calls === 1 ? "" : "s"} · {usage.total_tokens.toLocaleString()} tokens
        </p>
        {usage.cost_usd !== null && (
          <p className="tabular text-[13.5px] font-medium">
            ${usage.cost_usd < 0.01 ? usage.cost_usd.toFixed(4) : usage.cost_usd.toFixed(2)}
            {usage.estimated && (
              <span className="ml-1.5 text-[11.5px] font-normal text-muted-foreground">estimated</span>
            )}
          </p>
        )}
      </div>

      <div className="mt-3 space-y-1.5 border-t border-border pt-3">
        {usage.records.map((record) => (
          <div
            key={`${record.provider}:${record.model}:${record.role}`}
            className="flex flex-wrap items-baseline justify-between gap-2 text-[12px]"
          >
            <span className="min-w-0 truncate font-mono text-muted-foreground">
              {record.model} · {record.role}
            </span>
            <span className="tabular shrink-0 text-muted-foreground">
              {record.total_tokens.toLocaleString()} tok
              {record.cost_usd !== null && ` · $${record.cost_usd.toFixed(4)}`}
            </span>
          </div>
        ))}
      </div>

      {usage.unpriced_models.length > 0 && (
        <p className="mt-3 border-t border-border pt-3 text-[12px] leading-relaxed text-muted-foreground">
          No published price for {usage.unpriced_models.join(", ")}, so their tokens are counted but
          not costed. The total above is therefore a floor, not the whole bill.
        </p>
      )}
    </div>
  )
}
