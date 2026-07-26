"use client"

import { Check, ChevronDown, Cpu, RefreshCw, TriangleAlert } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"

import { api } from "@/lib/api"
import type { ModelListResponse } from "@/lib/types"
import { cn } from "@/lib/utils"

const ROLES = [
  { key: "manager", label: "Reasoning", hint: "Plans the analysis and writes the answer" },
  { key: "worker", label: "Code", hint: "Writes the Python that runs" },
] as const

function formatSize(bytes: number): string {
  if (!bytes) return ""
  const gb = bytes / 1024 ** 3
  return gb >= 1 ? `${gb.toFixed(1)}GB` : `${Math.round(bytes / 1024 ** 2)}MB`
}

/**
 * Lets the user pick which locally-installed model fills each role.
 *
 * The list comes from the running Ollama daemon rather than being hardcoded, so
 * whatever the user has pulled is what they can choose.
 */
export function ModelPicker() {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<ModelListResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [activeRole, setActiveRole] = useState<"manager" | "worker">("manager")
  const containerRef = useRef<HTMLDivElement>(null)

  const load = useCallback(async (refresh = false) => {
    setLoading(true)
    try {
      setData(await api.models(refresh))
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

  const select = async (name: string) => {
    await api.selectModels({ [activeRole]: name })
    await load()
  }

  const selected = data?.selected ?? {}
  const current = String(selected[activeRole] ?? "")
  const label = String(selected.manager ?? "model")

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
          className="absolute right-0 z-50 mt-1 w-80 overflow-hidden rounded-xl border border-border bg-popover shadow-lg"
        >
          <div className="flex items-center gap-1 border-b border-border p-1.5">
            {ROLES.map((role) => (
              <button
                key={role.key}
                type="button"
                onClick={() => setActiveRole(role.key)}
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
              onClick={() => void load(true)}
              aria-label="Refresh model list"
              className="flex h-7 w-7 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted"
            >
              <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
            </button>
          </div>

          <div className="max-h-72 overflow-y-auto p-1.5">
            {data?.error && (
              <div className="flex items-start gap-2 px-2 py-3 text-xs text-amber-600 dark:text-amber-400">
                <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>{data.error}</span>
              </div>
            )}

            {!loading && data && data.models.length === 0 && !data.error && (
              <p className="px-2 py-3 text-xs text-muted-foreground">
                No models found. Pull one first, e.g. <code>ollama pull qwen2.5-coder:1.5b</code>.
              </p>
            )}

            {data?.models.map((model) => (
              <button
                key={model.name}
                type="button"
                onClick={() => void select(model.name)}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left transition-colors hover:bg-muted"
              >
                <Check
                  className={cn(
                    "h-3.5 w-3.5 shrink-0",
                    model.name === current ? "text-emerald-500" : "text-transparent",
                  )}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-medium">{model.name}</span>
                  <span className="block truncate text-[10px] text-muted-foreground">
                    {[model.parameter_size, formatSize(model.size_bytes), ...model.capabilities]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </span>
              </button>
            ))}
          </div>

          <p className="border-t border-border px-3 py-2 text-[10px] text-muted-foreground">
            Provider: {data?.provider ?? "…"} · applies to this session
          </p>
        </div>
      )}
    </div>
  )
}
