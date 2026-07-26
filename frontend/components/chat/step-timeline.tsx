"use client"

import { Check, ChevronRight, Code2, Loader2, Play, Search, ShieldCheck, X } from "lucide-react"
import { useState } from "react"

import { cn } from "@/lib/utils"
import type { RunStep } from "@/lib/types"

const ICONS = {
  plan: Search,
  code: Code2,
  execute: Play,
  review: ShieldCheck,
  tool: Search,
} as const

interface StepTimelineProps {
  steps: RunStep[]
  code?: string
  stdout?: string
}

/**
 * Compact tool-call timeline, equivalent to the "Ran code" disclosures in
 * ChatGPT. Collapsed by default so it never competes with the answer.
 */
export function StepTimeline({ steps, code, stdout }: StepTimelineProps) {
  const [open, setOpen] = useState(false)

  if (steps.length === 0 && !code) return null

  const running = steps.some((step) => step.status === "running")
  const failed = steps.some((step) => step.status === "failed")
  const total = steps.reduce((sum, step) => sum + (step.durationMs ?? 0), 0)

  return (
    <div className="mb-3 overflow-hidden rounded-xl border border-border/60 bg-card/50">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
        aria-expanded={open}
      >
        {running ? (
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-indigo-500" />
        ) : failed ? (
          <X className="h-3.5 w-3.5 shrink-0 text-rose-500" />
        ) : (
          <Check className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
        )}
        <span>
          {running
            ? (steps.find((step) => step.status === "running")?.label ?? "Working")
            : `Ran ${steps.length} step${steps.length === 1 ? "" : "s"}`}
        </span>
        {!running && total > 0 && (
          <span className="text-muted-foreground/60">· {(total / 1000).toFixed(1)}s</span>
        )}
        <ChevronRight
          className={cn("ml-auto h-3.5 w-3.5 transition-transform duration-200", open && "rotate-90")}
        />
      </button>

      {open && (
        <div className="space-y-3 border-t border-border/60 px-3 py-3">
          <ol className="space-y-1.5">
            {steps.map((step) => {
              const Icon = ICONS[step.kind] ?? Play
              return (
                <li key={`${step.id}-${step.label}`} className="flex items-center gap-2 text-xs">
                  <Icon className="h-3 w-3 shrink-0 text-muted-foreground" />
                  <span
                    className={cn(
                      step.status === "failed" && "text-rose-500",
                      step.status === "running" && "text-indigo-500",
                    )}
                  >
                    {step.label}
                  </span>
                  {step.status === "running" && <Loader2 className="h-3 w-3 animate-spin" />}
                </li>
              )
            })}
          </ol>

          {code && (
            <pre className="max-h-72 overflow-auto rounded-lg bg-muted/70 p-3 text-[11.5px] leading-relaxed">
              <code className="font-mono">{code}</code>
            </pre>
          )}

          {stdout?.trim() && (
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Output
              </p>
              <pre className="max-h-56 overflow-auto rounded-lg bg-stone-950 p-3 text-[11.5px] leading-relaxed text-stone-200">
                <code className="font-mono">{stdout}</code>
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
