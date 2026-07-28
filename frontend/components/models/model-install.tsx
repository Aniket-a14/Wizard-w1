"use client"

import { Download, Info, Loader2, TriangleAlert, X } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { api } from "@/lib/api"
import type {
  ModelDownloadState,
  ProviderDownloadCapability,
  ProviderId,
} from "@/lib/types"
import { cn } from "@/lib/utils"

/**
 * How often the download list is re-read while something is running.
 *
 * Polled rather than streamed: a pull runs for minutes and survives a reload,
 * so a socket held open for the duration would be the fragile choice. When
 * nothing is running the poll stops entirely rather than idling at this rate.
 */
const POLL_INTERVAL_MS = 1200

type Suggestion = { name: string; label: string; note: string }

/**
 * A starter model per role, for the case this whole feature exists to fix: a
 * fresh install with no models at all, where the picker is empty and the
 * instructions used to be "go and use a different application".
 *
 * Deliberately small. These are what a laptop can actually run, and the point
 * is to get to a working first answer, not to a good one.
 */
const SUGGESTIONS: Partial<Record<ProviderId, Suggestion[]>> = {
  ollama: [
    { name: "qwen2.5:3b", label: "Reasoning", note: "1.9 GB · plans the analysis" },
    { name: "qwen2.5-coder:1.5b", label: "Code", note: "1.0 GB · writes the pandas" },
    { name: "nomic-embed-text", label: "Retrieval", note: "274 MB · optional, sharpens matching" },
  ],
  lmstudio: [
    {
      name: "https://huggingface.co/lmstudio-community/Qwen2.5-1.5B-Instruct-GGUF",
      label: "Reasoning",
      note: "~1.2 GB · plans the analysis",
    },
    {
      name: "https://huggingface.co/lmstudio-community/Qwen2.5-Coder-1.5B-Instruct-GGUF",
      label: "Code",
      note: "~1.2 GB · writes the pandas",
    },
  ],
}

function formatBytes(bytes: number): string {
  if (!bytes) return ""
  const gb = bytes / 1024 ** 3
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.round(bytes / 1024 ** 2)} MB`
}

/** The last segment of an HF URL, so a progress row is readable. */
function shortName(model: string): string {
  if (!model.startsWith("http")) return model
  return model.replace(/\/$/, "").split("/").slice(-1)[0] ?? model
}

/**
 * Installing a model without leaving Wizard.
 *
 * Getting a model was the one setup step that sent you out of a local-first
 * tool and into a terminal or the LM Studio window — and it is the step a
 * first-time user hits first, with an empty picker and nothing to select.
 *
 * The two providers differ in what they can report, and this shows the
 * difference rather than hiding it: Ollama streams byte counts, LM Studio
 * reports a percentage and nothing at all while it resolves a repo.
 */
export function ModelInstall({
  provider,
  installed,
  onInstalled,
  onCapability,
}: {
  provider: ProviderId | null
  /** Names already present on this provider, so a starter pick can say so. */
  installed: string[]
  onInstalled: () => void
  /**
   * Reports what this provider allows. Deleting lives on the model cards
   * rather than here, but only one component should ask the server.
   */
  onCapability?: (capability: ProviderDownloadCapability) => void
}) {
  const [downloads, setDownloads] = useState<ModelDownloadState[]>([])
  const [capability, setCapability] = useState<ProviderDownloadCapability | null>(null)
  const [name, setName] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)

  // Re-listing models is the parent's job, and it must happen exactly once per
  // download that finishes — not on every poll that still sees it as complete.
  const settled = useRef(new Set<string>())

  const refresh = useCallback(async () => {
    try {
      const response = await api.modelDownloads(provider ?? undefined)
      setDownloads(response.downloads)
      setCapability(response.capability)
      onCapability?.(response.capability)

      let finished = false
      for (const entry of response.downloads) {
        const key = `${entry.provider}:${entry.model}`
        if (entry.status === "completed" && !settled.current.has(key)) {
          settled.current.add(key)
          finished = true
        }
      }
      if (finished) onInstalled()
    } catch {
      // A failed poll is not worth a banner; the next one will say the same.
    }
  }, [onCapability, onInstalled, provider])

  const active = useMemo(
    () => downloads.some((entry) => entry.status === "queued" || entry.status === "downloading"),
    [downloads],
  )

  useEffect(() => {
    void refresh()
    if (!active) return
    const timer = setInterval(() => void refresh(), POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [active, refresh])

  const start = useCallback(
    async (model: string) => {
      const trimmed = model.trim()
      if (!trimmed) return
      setStarting(true)
      setError(null)
      try {
        await api.downloadModel(trimmed, provider ?? undefined)
        setName("")
        await refresh()
      } catch (exception) {
        setError(exception instanceof Error ? exception.message : "Could not start the download.")
      } finally {
        setStarting(false)
      }
    },
    [provider, refresh],
  )

  const cancel = useCallback(
    async (entry: ModelDownloadState) => {
      await api.cancelModelDownload(entry.model, entry.provider).catch(() => undefined)
      await refresh()
    },
    [refresh],
  )

  const suggestions = (provider && SUGGESTIONS[provider]) || []

  /**
   * Whether a starter pick is already here. Matched loosely on purpose: what
   * you ask for and what you end up with rarely match textually — `nomic-embed-text`
   * installs as `nomic-embed-text:latest` on Ollama, and an HF URL becomes an
   * id like `qwen2.5-1.5b-instruct` in LM Studio.
   */
  const isInstalled = useCallback(
    (candidate: string) => {
      const stem = shortName(candidate)
        .replace(/-GGUF$/i, "")
        .split(":")[0]
        .toLowerCase()
      return installed.some((existing) => existing.toLowerCase().split(":")[0] === stem)
    },
    [installed],
  )

  return (
    <section className="border-y border-border px-6 py-5 md:px-9">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="flex items-center gap-2 text-[13px] font-semibold tracking-[-0.01em]">
          <Download className="h-3.5 w-3.5 text-brand" />
          Install a model
        </h2>
        {capability?.can_download && (
          <p className="text-[11.5px] text-muted-foreground">
            Downloads run one at a time so they do not compete for the same disk.
          </p>
        )}
      </div>

      {/* Why the controls are absent, when they are. --------------------- */}
      {capability && !capability.can_download ? (
        <p className="mt-3 flex items-start gap-2.5 rounded-xl border border-border bg-card p-3.5 text-[12.5px] leading-relaxed text-muted-foreground">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{capability.reason}</span>
        </p>
      ) : (
        <>
          <div className="mt-3.5 flex flex-wrap gap-2">
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void start(name)
              }}
              placeholder={
                provider === "lmstudio"
                  ? "huggingface.co/owner/Model-GGUF"
                  : "qwen2.5:3b"
              }
              aria-label="Model to install"
              spellCheck={false}
              className="h-9 min-w-0 flex-1 rounded-lg border border-border bg-card px-3 font-mono text-[12.5px] shadow-xs outline-none transition-colors duration-[var(--duration-fast)] placeholder:font-sans placeholder:text-muted-foreground focus:border-brand/45"
            />
            <button
              type="button"
              onClick={() => void start(name)}
              disabled={!name.trim() || starting}
              className="flex h-9 items-center gap-2 rounded-lg bg-primary px-3.5 text-[13px] font-medium text-primary-foreground shadow-xs transition-opacity duration-[var(--duration-fast)] hover:opacity-90 disabled:opacity-40"
            >
              {starting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Download className="h-3.5 w-3.5" />
              )}
              Download
            </button>
          </div>

          {suggestions.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {suggestions.map((suggestion) => {
                const here = isInstalled(suggestion.name)
                return (
                  <button
                    key={suggestion.name}
                    type="button"
                    onClick={() => void start(suggestion.name)}
                    disabled={starting || here}
                    title={suggestion.name}
                    className="rounded-lg border border-border bg-card px-2.5 py-1.5 text-left shadow-xs transition-colors duration-[var(--duration-fast)] hover:border-brand/40 disabled:opacity-45 disabled:hover:border-border"
                  >
                    <span className="block text-[11.5px] font-medium">{suggestion.label}</span>
                    <span className="block text-[10.5px] text-muted-foreground">
                      {here ? "already installed" : suggestion.note}
                    </span>
                  </button>
                )
              })}
            </div>
          )}

          {provider === "lmstudio" && (
            <p className="mt-2.5 text-[11.5px] leading-relaxed text-muted-foreground">
              LM Studio picks the quantization that suits this machine. It reports a percentage
              rather than byte counts, and stays quiet while it resolves the repository.
            </p>
          )}
        </>
      )}

      {error && (
        <p className="mt-3 flex items-start gap-2.5 rounded-xl border border-warning/25 bg-warning/8 p-3 text-[12.5px] leading-relaxed text-warning">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{error}</span>
        </p>
      )}

      {downloads.length > 0 && (
        <ul className="mt-4 space-y-2">
          {downloads.map((entry) => (
            <DownloadRow
              key={`${entry.provider}:${entry.model}`}
              entry={entry}
              onCancel={() => void cancel(entry)}
            />
          ))}
        </ul>
      )}
    </section>
  )
}

const STATUS_TONE: Record<ModelDownloadState["status"], string> = {
  queued: "text-muted-foreground",
  downloading: "text-brand",
  completed: "text-success",
  failed: "text-warning",
  cancelled: "text-muted-foreground",
}

function DownloadRow({
  entry,
  onCancel,
}: {
  entry: ModelDownloadState
  onCancel: () => void
}) {
  const running = entry.status === "queued" || entry.status === "downloading"
  const bytes =
    entry.total_bytes > 0
      ? `${formatBytes(entry.completed_bytes)} / ${formatBytes(entry.total_bytes)}`
      : ""

  return (
    <li className="rounded-xl border border-border bg-card p-3 shadow-xs">
      <div className="flex items-center gap-3">
        <span className="min-w-0 flex-1 truncate font-mono text-[12.5px]">
          {shortName(entry.model)}
        </span>
        <span className={cn("shrink-0 text-[11.5px] font-medium", STATUS_TONE[entry.status])}>
          {entry.percent !== null && running ? `${entry.percent.toFixed(0)}%` : entry.detail || entry.status}
        </span>
        {running && (
          <button
            type="button"
            onClick={onCancel}
            aria-label={`Cancel downloading ${shortName(entry.model)}`}
            className="shrink-0 rounded-md p-1 text-muted-foreground transition-colors duration-[var(--duration-fast)] hover:bg-muted hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {running && (
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-muted">
          {/* An indeterminate stripe while nothing measurable has been
              reported — a bar pinned at 0% reads as broken. */}
          <div
            className={cn(
              "h-full rounded-full bg-brand transition-[width] duration-[var(--duration-base)]",
              entry.percent === null && "w-1/3 animate-pulse",
            )}
            style={entry.percent === null ? undefined : { width: `${entry.percent}%` }}
          />
        </div>
      )}

      {(bytes || entry.error) && (
        <p
          className={cn(
            "mt-1.5 text-[11px]",
            entry.error ? "text-warning" : "text-muted-foreground",
          )}
        >
          {entry.error ?? bytes}
        </p>
      )}
    </li>
  )
}
