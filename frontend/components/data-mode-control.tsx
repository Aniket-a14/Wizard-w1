"use client"

import { Check, Cloud, HardDrive, Shuffle } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"

import { api } from "@/lib/api"
import type { DataMode, DataModeInfo, UsageTotals } from "@/lib/types"
import { setUsage, useUsage } from "@/lib/usage-store"
import { cn } from "@/lib/utils"

/**
 * The trust-critical control, and the reason it lives in the rail.
 *
 * Which models a session may reach — and therefore whether anything leaves this
 * machine — is not a preference to be found three screens deep. It renders on
 * every route because the rail does, and the rail is mounted once from the root
 * layout, so this costs no remount and never interrupts the chat socket.
 *
 * The cost line sits with it deliberately: what you are spending is a
 * consequence of this choice, not a separate topic.
 */

const MODES: { key: DataMode; label: string; icon: typeof HardDrive; consequence: string }[] = [
  {
    key: "local-only",
    label: "Local only",
    icon: HardDrive,
    consequence: "Every model runs here. Cloud providers are refused, not merely unused, and web search is off.",
  },
  {
    key: "cloud-only",
    label: "Cloud only",
    icon: Cloud,
    consequence: "Every model is called over the network. Nothing needs to be installed on this machine.",
  },
  {
    key: "hybrid",
    label: "Hybrid",
    icon: Shuffle,
    consequence: "You pick a provider per role. Cloud-bound prompts follow the data policy on Settings.",
  },
]

function iconFor(mode: DataMode) {
  return MODES.find((option) => option.key === mode)?.icon ?? HardDrive
}

export function DataModeControl({ onChanged }: { onChanged?: () => void }) {
  const [info, setInfo] = useState<DataModeInfo | null>(null)
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  // Read from the shared store rather than held here: the chat socket learns
  // what a turn cost the moment it ends, and this component is nowhere near it.
  const usage = useUsage()

  const refresh = useCallback(async () => {
    const [mode, totals] = await Promise.all([
      api.dataMode().catch(() => null),
      api.usage().catch(() => null),
    ])
    if (mode) setInfo(mode)
    if (totals) setUsage(totals)
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // Closed on an outside click rather than on a blur: the popover contains
  // buttons, and a blur fires before their click lands.
  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener("pointerdown", onPointerDown)
    return () => document.removeEventListener("pointerdown", onPointerDown)
  }, [open])

  const choose = async (mode: DataMode) => {
    if (mode === info?.mode) {
      setOpen(false)
      return
    }
    setSaving(true)
    try {
      setInfo(await api.setDataMode({ mode }))
      setOpen(false)
      // A mode switch can clear a role's provider, so anything showing model
      // selection has to re-read rather than trust what it already has.
      onChanged?.()
      void refresh()
    } catch {
      void refresh()
    } finally {
      setSaving(false)
    }
  }

  const Icon = iconFor(info?.mode ?? "local-only")
  const localOnly = info?.mode === "local-only"

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={info?.description ?? "Where your data may go"}
        className={cn(
          "flex w-full items-center gap-2 rounded-lg border px-2.5 py-2 text-left",
          "transition-colors duration-[var(--duration-fast)]",
          localOnly
            ? "border-success/30 bg-success/5 hover:bg-success/10"
            : "border-warning/30 bg-warning/5 hover:bg-warning/10",
        )}
      >
        <Icon className={cn("h-3.5 w-3.5 shrink-0", localOnly ? "text-success" : "text-warning")} />
        <span className="min-w-0 flex-1">
          <span className="block text-[11.5px] font-medium leading-tight">
            {MODES.find((option) => option.key === info?.mode)?.label ?? "…"}
          </span>
          <span className="mt-0.5 block truncate text-[10.5px] leading-tight text-muted-foreground">
            <CostLine usage={usage} localOnly={localOnly} />
          </span>
        </span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Data mode"
          className="glass absolute bottom-full left-0 z-50 mb-2 w-[290px] rounded-xl border border-border p-1.5 shadow-lg reveal-scale"
        >
          <p className="px-2 pb-1.5 pt-1 text-[10.5px] uppercase tracking-[0.12em] text-muted-foreground">
            Where your data may go
          </p>
          {MODES.map((option) => {
            const OptionIcon = option.icon
            const active = option.key === info?.mode
            return (
              <button
                key={option.key}
                type="button"
                disabled={saving}
                onClick={() => void choose(option.key)}
                className={cn(
                  "flex w-full items-start gap-2.5 rounded-lg px-2 py-2 text-left",
                  "transition-colors duration-[var(--duration-fast)] disabled:opacity-50",
                  active ? "bg-accent/60" : "hover:bg-accent/40",
                )}
              >
                <OptionIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5 text-[12.5px] font-medium">
                    {option.label}
                    {active && <Check className="h-3 w-3 text-brand" />}
                  </span>
                  <span className="mt-0.5 block text-[11px] leading-snug text-muted-foreground">
                    {option.consequence}
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

/**
 * Under local-only this says nothing was sent — it does not render "$0.00".
 * A zero reads as a computed figure, and the honest statement is that there is
 * no meter, not that the meter reads nothing.
 */
function CostLine({ usage, localOnly }: { usage: UsageTotals | null; localOnly: boolean }) {
  if (localOnly) return <>Nothing leaves this machine</>
  if (!usage || usage.calls === 0) return <>No calls yet this session</>

  const tokens =
    usage.total_tokens >= 1000
      ? `${(usage.total_tokens / 1000).toFixed(1)}k tokens`
      : `${usage.total_tokens} tokens`

  // Cost is null when nothing billable ran, and also when a cloud model's price
  // is not published. Both are reported as tokens rather than as a guess.
  if (usage.cost_usd === null) return <>{tokens}</>
  return (
    <>
      {tokens} · ${usage.cost_usd < 0.01 ? usage.cost_usd.toFixed(4) : usage.cost_usd.toFixed(2)}
      {usage.estimated ? " est." : ""}
    </>
  )
}
