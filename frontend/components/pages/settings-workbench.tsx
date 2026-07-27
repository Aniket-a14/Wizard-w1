"use client"

import { Loader2, RotateCcw, ShieldAlert, ShieldCheck, Volume2, VolumeX } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { PageHeader, Section } from "@/components/page-header"
import { api, clearStoredSessionId, getStoredSessionId } from "@/lib/api"
import type { ServerConfig, SessionInfo } from "@/lib/types"
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
  const { soundOn, toggleSound } = useSound()

  const refresh = useCallback(async () => {
    const [nextConfig, nextSession] = await Promise.allSettled([api.config(), api.session()])
    if (nextConfig.status === "fulfilled") setConfig(nextConfig.value)
    if (nextSession.status === "fulfilled") setSession(nextSession.value)
    setSessionId(getStoredSessionId())
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
        title="Execution"
        description="Where generated code runs. Docker is not required — set EXECUTION_BACKEND in backend/.env."
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
                ? config.execution_backend_setting === "auto"
                  ? `auto → ${config.execution_backend}`
                  : config.execution_backend_setting
                : "—"
            }
            mono
          />
          <Fact
            label="Toolkit tier"
            value={config ? TIER_TOOLKIT_LABELS[config.sandbox_tier] ?? config.sandbox_tier : "—"}
          />
          <Fact label="Memory per runtime" value={config?.sandbox_mem_limit || "—"} mono />
          <Fact label="Concurrent sessions" value={config ? String(config.max_sessions) : "—"} />
          <Fact label="Plot format" value={config?.plot_format ?? "—"} />
        </dl>

        {config && <IsolationNote backend={config.execution_backend} />}
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
            label="Approval gate"
            value={config ? (config.agent_require_approval ? "Required" : "Off") : "—"}
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
          are treated as the middle tier. Web search always asks before it runs, whatever the approval
          gate is set to.
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

const BACKEND_LABELS: Record<string, string> = {
  docker: "Docker container",
  local: "Local subprocess",
  inprocess: "In-process (no isolation)",
}

const BACKEND_TONE: Record<string, "ok" | "warn" | undefined> = {
  docker: "ok",
  local: "ok",
  inprocess: "warn",
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
 * Says what the isolation actually is, per backend. The local runtime is a
 * supported way to run rather than a failure, so it gets a statement of what it
 * does and does not protect — not a warning banner.
 */
function IsolationNote({ backend }: { backend: string }) {
  if (backend === "docker") {
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

  if (backend === "local") {
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
        <code className="font-mono text-[11.5px]">EXECUTION_BACKEND=local</code> to run it in a
        subprocess instead, or start Docker.
      </span>
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
