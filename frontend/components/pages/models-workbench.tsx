"use client"

import { Check, Cpu, Loader2, RefreshCw, TriangleAlert, Zap } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { PageHeader } from "@/components/page-header"
import { api } from "@/lib/api"
import type { ModelInfo, ModelListResponse, ProviderId } from "@/lib/types"
import { useSound } from "@/lib/use-sound"
import { cn } from "@/lib/utils"

const ROLES = [
  {
    key: "manager" as const,
    label: "Reasoning",
    blurb: "Reads the schema, plans the analysis and writes the final answer.",
    wants: "reasoning",
  },
  {
    key: "worker" as const,
    label: "Code",
    blurb: "Writes the pandas that actually runs, and repairs it when it fails.",
    wants: "code",
  },
]

const PROVIDER_LABELS: Record<ProviderId, string> = {
  ollama: "Ollama",
  lmstudio: "LM Studio",
  openai: "OpenAI",
  custom_gateway: "Gateway",
}

const EMPTY_HINTS: Record<ProviderId, string> = {
  ollama: "Nothing pulled yet, or the daemon is not running. Any model works — try `ollama pull qwen3:8b`.",
  lmstudio:
    "Start the server from LM Studio's Developer tab, and enable “Serve on Local Network” so the backend can reach it from its container.",
  openai: "Set GATEWAY_API_URL and GATEWAY_API_KEY in backend/.env.",
  custom_gateway: "Set GATEWAY_API_URL and GATEWAY_API_KEY in backend/.env.",
}

function formatSize(bytes: number): string {
  if (!bytes) return ""
  const gb = bytes / 1024 ** 3
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.round(bytes / 1024 ** 2)} MB`
}

function formatContext(tokens: number): string {
  if (!tokens) return ""
  return tokens >= 1024 ? `${Math.round(tokens / 1024)}k context` : `${tokens} context`
}

/**
 * The full model surface: every provider, every installed model, and which
 * role each one fills.
 *
 * The header dropdown is for a quick swap mid-conversation. This is where you
 * come to actually see what is available — the dropdown cannot show
 * quantization, context length and load state without becoming a page anyway.
 */
export function ModelsWorkbench() {
  const [data, setData] = useState<ModelListResponse | null>(null)
  const [provider, setProvider] = useState<ProviderId | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<string | null>(null)
  const { playSound } = useSound()

  const load = useCallback(async (target?: ProviderId, refresh = false) => {
    setLoading(true)
    try {
      const response = await api.models(refresh, target)
      setData(response)
      setProvider(response.provider as ProviderId)
    } catch {
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const assign = useCallback(
    async (role: "manager" | "worker", model: string) => {
      if (!provider) return
      setSaving(`${role}:${model}`)
      try {
        await api.selectModels({ [role]: model, [`${role}_provider`]: provider })
        await load(provider)
        playSound("click")
      } finally {
        setSaving(null)
      }
    },
    [load, playSound, provider],
  )

  const setTemperature = useCallback(
    async (value: number) => {
      await api.selectModels({ temperature: value })
      setData((current) =>
        current ? { ...current, selected: { ...current.selected, temperature: value } } : current,
      )
    },
    [],
  )

  const selected = data?.selected ?? {}
  const providers = data?.providers ?? []
  const models = data?.models ?? []
  const temperature = typeof selected.temperature === "number" ? selected.temperature : 0

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <PageHeader
        eyebrow="Configuration"
        title="Models"
        description="Each role runs on whichever backend you point it at. Reasoning can sit on Ollama while code generation runs in LM Studio — they are resolved separately on every request."
        actions={
          <button
            type="button"
            onClick={() => void load(provider ?? undefined, true)}
            className="flex h-9 items-center gap-2 rounded-lg border border-border bg-card px-3.5 text-[13px] font-medium shadow-xs transition-colors duration-[var(--duration-fast)] hover:border-brand/40"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            Rescan
          </button>
        }
      />

      {/* Role assignment ---------------------------------------------------- */}
      <div className="grid gap-3 px-6 py-6 md:grid-cols-2 md:px-9">
        {ROLES.map((role) => {
          const model = String(selected[role.key] ?? "—")
          const roleProvider = String(selected[`${role.key}_provider`] ?? "") as ProviderId
          return (
            <div key={role.key} className="ring-gradient rounded-xl p-4 shadow-sm">
              <div className="flex items-center gap-2">
                <Cpu className="h-3.5 w-3.5 text-brand" />
                <h2 className="text-[13px] font-semibold tracking-[-0.01em]">{role.label}</h2>
              </div>
              <p className="mt-2 text-[12.5px] leading-relaxed text-muted-foreground">{role.blurb}</p>
              <p className="mt-3.5 truncate font-mono text-[13px] font-medium">{model}</p>
              <p className="mt-1 text-[11.5px] text-muted-foreground">
                on {PROVIDER_LABELS[roleProvider] ?? (roleProvider || "—")}
              </p>
            </div>
          )
        })}
      </div>

      {/* Temperature -------------------------------------------------------- */}
      <div className="border-y border-border px-6 py-5 md:px-9">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="flex items-center gap-2 text-[13px] font-semibold tracking-[-0.01em]">
              <Zap className="h-3.5 w-3.5 text-brand" />
              Temperature
            </h2>
            <p className="mt-1.5 max-w-lg text-[12.5px] leading-relaxed text-muted-foreground">
              Applies to every role. Analysis code wants determinism — 0 is the right answer far more
              often than it is for prose.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={temperature}
              onChange={(event) => void setTemperature(Number(event.target.value))}
              aria-label="Model temperature"
              className="h-1.5 w-44 cursor-pointer appearance-none rounded-full bg-muted accent-[var(--brand)]"
            />
            <span className="tabular w-10 text-right text-[13px] font-medium">
              {temperature.toFixed(2)}
            </span>
          </div>
        </div>
      </div>

      {/* Provider browser --------------------------------------------------- */}
      <div className="px-6 py-6 md:px-9">
        <div className="mb-4 flex flex-wrap items-center gap-1.5">
          {providers.map((entry) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => void load(entry.id)}
              title={entry.base_url || "No endpoint configured"}
              className={cn(
                "rounded-lg px-3 py-1.5 text-[12.5px] font-medium transition-colors duration-[var(--duration-fast)]",
                provider === entry.id
                  ? "bg-primary text-primary-foreground shadow-xs"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
                !entry.configured && provider !== entry.id && "opacity-45",
              )}
            >
              {PROVIDER_LABELS[entry.id] ?? entry.id}
            </button>
          ))}
          {provider && (
            <span className="ml-auto truncate font-mono text-[11px] text-muted-foreground">
              {providers.find((entry) => entry.id === provider)?.base_url}
            </span>
          )}
        </div>

        {data?.error && (
          <div className="flex items-start gap-2.5 rounded-xl border border-warning/25 bg-warning/8 p-3.5 text-[13px] leading-relaxed text-warning">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{data.error}</span>
          </div>
        )}

        {!loading && models.length === 0 && !data?.error && provider && (
          <p className="rounded-xl border border-border bg-card p-5 text-[13px] leading-relaxed text-muted-foreground">
            {EMPTY_HINTS[provider]}
          </p>
        )}

        {loading && models.length === 0 && (
          <div className="flex justify-center py-12">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        )}

        <div className="grid gap-2.5 lg:grid-cols-2">
          {models.map((model) => (
            <ModelCard
              key={model.name}
              model={model}
              assignedTo={ROLES.filter(
                (role) =>
                  selected[role.key] === model.name && selected[`${role.key}_provider`] === provider,
              ).map((role) => role.label)}
              saving={saving}
              onAssign={assign}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

function ModelCard({
  model,
  assignedTo,
  saving,
  onAssign,
}: {
  model: ModelInfo
  assignedTo: string[]
  saving: string | null
  onAssign: (role: "manager" | "worker", model: string) => void
}) {
  const facts = [
    model.parameter_size,
    formatSize(model.size_bytes),
    model.quantization,
    formatContext(model.context_length),
  ].filter(Boolean)

  return (
    <article
      className={cn(
        "rounded-xl border bg-card p-4 shadow-xs transition-colors duration-[var(--duration-base)]",
        assignedTo.length > 0 ? "border-brand/45" : "border-border hover:border-brand/25",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate font-mono text-[13px] font-medium">{model.name}</h3>
          {facts.length > 0 && (
            <p className="mt-1.5 truncate text-[11.5px] text-muted-foreground">{facts.join(" · ")}</p>
          )}
        </div>
        {/* LM Studio loads on first use; that stall is worth warning about. */}
        {model.loaded === false && (
          <span className="shrink-0 rounded-md px-1.5 py-0.5 text-[9.5px] text-muted-foreground ring-1 ring-border">
            not loaded
          </span>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1">
        {model.capabilities.map((capability) => (
          <span
            key={capability}
            className="rounded-md bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground"
          >
            {capability}
          </span>
        ))}
      </div>

      <div className="mt-3.5 flex items-center gap-1.5 border-t border-border pt-3">
        {model.capabilities.includes("embedding") ? (
          <p className="text-[11.5px] text-muted-foreground">
            Embedding model — not usable as a chat role.
          </p>
        ) : (
          ROLES.map((role) => {
            const isAssigned = assignedTo.includes(role.label)
            const isSaving = saving === `${role.key}:${model.name}`
            return (
              <button
                key={role.key}
                type="button"
                onClick={() => onAssign(role.key, model.name)}
                disabled={isAssigned || isSaving}
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-2 py-1 text-[11.5px] font-medium",
                  "transition-colors duration-[var(--duration-fast)]",
                  isAssigned
                    ? "cursor-default bg-brand-soft text-brand"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {isSaving ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : isAssigned ? (
                  <Check className="h-3 w-3" />
                ) : null}
                {isAssigned ? role.label : `Use for ${role.label.toLowerCase()}`}
              </button>
            )
          })
        )}
      </div>
    </article>
  )
}
