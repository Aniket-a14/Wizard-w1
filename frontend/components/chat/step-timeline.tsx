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
    <div
      className={cn(
        "mb-3 overflow-hidden rounded-xl border bg-card/60 transition-colors duration-[var(--duration-base)]",
        running ? "border-brand/30" : failed ? "border-destructive/25" : "border-border",
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left text-[12.5px] font-medium text-muted-foreground transition-colors duration-[var(--duration-fast)] hover:text-foreground"
        aria-expanded={open}
      >
        {running ? (
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-brand" />
        ) : failed ? (
          <X className="h-3.5 w-3.5 shrink-0 text-destructive" />
        ) : (
          <Check className="h-3.5 w-3.5 shrink-0 text-success" />
        )}
        <span>
          {running
            ? (steps.find((step) => step.status === "running")?.label ?? "Working")
            : `Ran ${steps.length} step${steps.length === 1 ? "" : "s"}`}
        </span>
        {!running && total > 0 && (
          <span className="tabular text-muted-foreground/70">· {(total / 1000).toFixed(1)}s</span>
        )}
        <ChevronRight
          className={cn(
            "ml-auto h-3.5 w-3.5 transition-transform duration-[var(--duration-base)] ease-[var(--ease-out-expo)]",
            open && "rotate-90",
          )}
        />
      </button>

      {open && (
        <div className="space-y-3.5 border-t border-border px-3.5 py-3.5">
          {/* A rail down the left connects the steps into one run rather than
              leaving them as an unrelated list of icons. */}
          <ol className="relative space-y-2.5 before:absolute before:bottom-2 before:left-[5.5px] before:top-2 before:w-px before:bg-border">
            {steps.map((step) => {
              const Icon = ICONS[step.kind] ?? Play
              return (
                <li key={`${step.id}-${step.label}`} className="relative flex items-center gap-2.5 text-[12.5px]">
                  <span
                    className={cn(
                      "z-10 flex h-3 w-3 shrink-0 items-center justify-center rounded-full bg-card ring-2 ring-card",
                      step.status === "failed"
                        ? "text-destructive"
                        : step.status === "running"
                          ? "text-brand"
                          : "text-muted-foreground",
                    )}
                  >
                    <Icon className="h-3 w-3" />
                  </span>
                  <span
                    className={cn(
                      step.status === "failed" && "text-destructive",
                      step.status === "running" && "text-brand",
                    )}
                  >
                    {step.label}
                  </span>
                  {step.status === "running" && <Loader2 className="h-3 w-3 animate-spin text-brand" />}
                  {step.durationMs ? (
                    <span className="tabular ml-auto text-[11px] text-muted-foreground/70">
                      {(step.durationMs / 1000).toFixed(1)}s
                    </span>
                  ) : null}
                </li>
              )
            })}
          </ol>

          {code && (
            <div>
              <p className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                Generated code
              </p>
              <pre className="max-h-72 overflow-auto rounded-lg border border-border bg-muted/60 p-3 text-[11.5px] leading-relaxed">
                <code className="font-mono">{code}</code>
              </pre>
            </div>
          )}

          {stdout?.trim() && (
            <div>
              <p className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                Output
              </p>
              <pre className="max-h-56 overflow-auto rounded-lg bg-[oklch(0.19_0.012_275)] p-3 text-[11.5px] leading-relaxed text-[oklch(0.9_0.01_85)]">
                <code className="font-mono">{stdout}</code>
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
