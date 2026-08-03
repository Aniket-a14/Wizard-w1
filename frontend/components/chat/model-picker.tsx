"use client"

import { Check, ChevronDown, Cpu, RefreshCw, TriangleAlert } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"

import { api } from "@/lib/api"
import type { ModelListResponse, ProviderId, ProviderInfo } from "@/lib/types"
import { cn } from "@/lib/utils"

const ROLES = [
  { key: "manager", label: "Reasoning", hint: "Plans the analysis and writes the answer" },
  { key: "worker", label: "Code", hint: "Writes the Python that runs" },
] as const

/**
 * Labels and empty-state hints come from the backend's provider table. There
 * used to be a copy of both maps here and another on /models, and adding a
 * backend meant editing all three.
 */
function labelOf(providers: ProviderInfo[], id: string): string {
  return providers.find((entry) => entry.id === id)?.label ?? id
}

function emptyHint(entry: ProviderInfo | undefined): string {
  if (!entry) return "No models found."
  if (entry.requires_key && !entry.has_key) {
    return `${entry.label} needs an API key. Add one on the Models page.`
  }
  if (entry.id === "ollama") return "No models found. Pull one first — any model works, e.g. `ollama pull qwen3:8b`."
  if (entry.id === "lmstudio") {
    return "No models found. Start the LM Studio server (Developer tab) and enable “Serve on Local Network” so the backend can reach it."
  }
  return `No models found on ${entry.label}. Check its endpoint and key on the Models page.`
}

function formatSize(bytes: number): string {
  if (!bytes) return ""
  const gb = bytes / 1024 ** 3
  return gb >= 1 ? `${gb.toFixed(1)}GB` : `${Math.round(bytes / 1024 ** 2)}MB`
}

function formatContext(tokens: number): string {
  if (!tokens) return ""
  return tokens >= 1000 ? `${Math.round(tokens / 1024)}k ctx` : `${tokens} ctx`
}

/**
 * Lets the user pick which model fills each role, on which backend.
 *
 * The list is fetched per provider from the daemon itself rather than being
 * hardcoded, so whatever the user has installed is what they can choose. Roles
 * carry their provider independently: picking an LM Studio model for `worker`
 * leaves `manager` on Ollama.
 */
export function ModelPicker() {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<ModelListResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [activeRole, setActiveRole] = useState<"manager" | "worker">("manager")
  // `null` means "whatever the server says this role is using". It only becomes
  // a concrete id once the user browses to another provider, so opening the menu
  // always lands on the backend the role is actually running on.
  const [browsing, setBrowsing] = useState<ProviderId | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const load = useCallback(async (refresh = false, provider?: ProviderId) => {
    setLoading(true)
    try {
      setData(await api.models(refresh, provider))
    } catch {
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open && !data) void load()
  }, [open, data, load])

  useEffect(() => {
    if (!open) return
    const onClick = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false)
    }
    document.addEventListener("mousedown", onClick)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onClick)
      document.removeEventListener("keydown", onKey)
    }
  }, [open])

  const selected = data?.selected ?? {}
  const roleProvider = String(selected[`${activeRole}_provider`] ?? data?.provider ?? "") as ProviderId
  const shownProvider = browsing ?? roleProvider
  const current = String(selected[activeRole] ?? "")
  const label = String(selected.manager ?? "model")

  const select = async (name: string) => {
    // Always send the provider alongside the name: the model list on screen may
    // belong to a different backend than the one this role is currently on, and
    // a name without a provider would be sent to the wrong daemon.
    await api.selectModels({ [activeRole]: name, [`${activeRole}_provider`]: shownProvider })
    setBrowsing(null)
    await load(false, shownProvider)
  }

  const showProvider = async (provider: ProviderId) => {
    setBrowsing(provider)
    await load(false, provider)
  }

  const switchRole = (role: "manager" | "worker") => {
    setActiveRole(role)
    // Drop the browse override so the new role opens on its own provider.
    setBrowsing(null)
    void load(false, String(selected[`${role}_provider`] ?? "") as ProviderId)
  }

  const providers = data?.providers ?? []
  const mixed =
    Boolean(selected.manager_provider) &&
    Boolean(selected.worker_provider) &&
    selected.manager_provider !== selected.worker_provider

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <Cpu className="h-3.5 w-3.5" />
        <span className="max-w-[160px] truncate">{label}</span>
        <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 z-50 mt-1.5 w-80 overflow-hidden rounded-xl border border-border bg-popover shadow-lg reveal-in"
        >
          <div className="flex items-center gap-1 border-b border-border p-1.5">
            {ROLES.map((role) => (
              <button
                key={role.key}
                type="button"
                onClick={() => switchRole(role.key)}
                title={role.hint}
                className={cn(
                  "flex-1 rounded-lg px-2 py-1.5 text-xs font-medium transition-colors",
                  activeRole === role.key
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {role.label}
              </button>
            ))}
            <button
              type="button"
              onClick={() => void load(true, shownProvider)}
              aria-label="Refresh model list"
              className="flex h-7 w-7 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted"
            >
              <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
            </button>
          </div>

          {providers.length > 1 && (
            <div className="flex flex-wrap gap-1 border-b border-border px-1.5 py-1.5">
              {providers
                // A provider the data mode forbids is not offered here at all:
                // this menu exists to be clicked, and every choice in it should
                // be one the session can actually make.
                .filter((provider) => provider.allowed)
                .map((provider) => (
                  <button
                    key={provider.id}
                    type="button"
                    onClick={() => void showProvider(provider.id)}
                    title={provider.base_url || "No endpoint configured"}
                    className={cn(
                      "rounded-md px-2 py-1 text-[11px] font-medium transition-colors duration-[var(--duration-fast)]",
                      shownProvider === provider.id
                        ? "bg-foreground text-background"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground",
                      !provider.configured && shownProvider !== provider.id && "opacity-40",
                    )}
                  >
                    {provider.label}
                  </button>
                ))}
            </div>
          )}

          <div className="max-h-72 overflow-y-auto p-1.5">
            {data?.error && (
              <div className="flex items-start gap-2 px-2 py-3 text-[12px] leading-relaxed text-warning">
                <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>{data.error}</span>
              </div>
            )}

            {!loading && data && data.models.length === 0 && !data.error && (
              <p className="px-2 py-3 text-xs text-muted-foreground">
                {emptyHint(providers.find((entry) => entry.id === shownProvider))}
              </p>
            )}

            {data?.models.map((model) => (
              <button
                key={model.name}
                type="button"
                onClick={() => void select(model.name)}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left transition-colors duration-[var(--duration-fast)] hover:bg-accent/60"
              >
                <Check
                  className={cn(
                    "h-3.5 w-3.5 shrink-0",
                    model.name === current && shownProvider === roleProvider
                      ? "text-success"
                      : "text-transparent",
                  )}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-medium">{model.name}</span>
                  <span className="block truncate text-[10px] text-muted-foreground">
                    {[
                      model.parameter_size,
                      formatSize(model.size_bytes),
                      formatContext(model.context_length),
                      ...model.capabilities,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </span>
                {/* LM Studio loads on first use; that stall is worth warning about up front. */}
                {model.loaded === false && (
                  <span className="shrink-0 rounded px-1 py-0.5 text-[9px] text-muted-foreground ring-1 ring-border">
                    not loaded
                  </span>
                )}
              </button>
            ))}
          </div>

          <p className="border-t border-border px-3 py-2 text-[10px] text-muted-foreground">
            {mixed
              ? `Reasoning on ${labelOf(providers, String(selected.manager_provider))} · code on ${labelOf(providers, String(selected.worker_provider))}`
              : `Provider: ${shownProvider ? labelOf(providers, shownProvider) : "…"} · applies to this session`}
          </p>
        </div>
      )}
    </div>
  )
}
