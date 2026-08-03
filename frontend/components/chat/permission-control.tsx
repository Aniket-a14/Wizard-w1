"use client"

import { Check, ShieldAlert, ShieldCheck, SlidersHorizontal } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"

import { api } from "@/lib/api"
import type { PermissionProfile, PermissionsInfo } from "@/lib/types"
import { cn } from "@/lib/utils"

/**
 * How much the agent asks before it acts.
 *
 * Sits beside the depth control because the two are the composer's two dials and
 * they are genuinely independent: depth is how hard the agent works on a
 * question, this is how often it stops to ask permission along the way. The same
 * analysis run deep-and-auto-approve or fast-and-ask-always should reach the same
 * quality of answer and differ only in how often it interrupts.
 *
 * A popover rather than a third segmented group: three of those across one row
 * does not fit, and unlike depth this is a setting people change rarely.
 *
 * The full per-category matrix lives on Settings. This is the profile switch.
 */

const PROFILES: { key: PermissionProfile; label: string; icon: typeof ShieldCheck; consequence: string }[] = [
  {
    key: "ask-always",
    label: "Ask always",
    icon: ShieldCheck,
    consequence: "Stops for consent before installing anything, reaching the network, or writing outside its workspace.",
  },
  {
    key: "auto-approve",
    label: "Auto approve",
    icon: ShieldAlert,
    consequence: "Acts without asking. Writing to an external database is still never covered by this.",
  },
  {
    key: "custom",
    label: "Custom",
    icon: SlidersHorizontal,
    consequence: "You decide per category. Set them up on the Settings page.",
  },
]

function profileFor(profile: PermissionProfile | undefined) {
  return PROFILES.find((option) => option.key === profile) ?? PROFILES[0]
}

export function PermissionControl() {
  const [info, setInfo] = useState<PermissionsInfo | null>(null)
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const refresh = useCallback(async () => {
    const next = await api.permissions().catch(() => null)
    if (next) setInfo(next)
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

  const choose = async (profile: PermissionProfile) => {
    if (profile === info?.profile) {
      setOpen(false)
      return
    }
    setSaving(true)
    try {
      setInfo(await api.setPermissions({ profile }))
      setOpen(false)
    } catch {
      void refresh()
    } finally {
      setSaving(false)
    }
  }

  const current = profileFor(info?.profile)
  const Icon = current.icon

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={info?.description ?? "How much the agent asks before acting"}
        className={cn(
          "flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[11.5px] font-medium",
          "transition-colors duration-[var(--duration-fast)]",
          "text-muted-foreground hover:bg-muted hover:text-foreground",
        )}
      >
        <Icon className="h-3.5 w-3.5 shrink-0" />
        <span className="hidden sm:inline">{current.label}</span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Permission profile"
          className="glass absolute bottom-full right-0 z-50 mb-2 w-[300px] rounded-xl border border-border p-1.5 shadow-lg reveal-scale"
        >
          <p className="px-2 pb-1.5 pt-1 text-[10.5px] uppercase tracking-[0.12em] text-muted-foreground">
            Before the agent acts
          </p>
          {PROFILES.map((option) => {
            const OptionIcon = option.icon
            const active = option.key === info?.profile
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
          <p className="px-2 pb-1 pt-1.5 text-[10.5px] leading-snug text-muted-foreground/80">
            Separate from the data mode in the sidebar. That one decides what is possible at all; this
            decides what you are asked about.
          </p>
        </div>
      )}
    </div>
  )
}
