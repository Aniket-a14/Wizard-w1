"use client"

import { AlertTriangle, BadgeCheck, HelpCircle, Info, ShieldAlert } from "lucide-react"
import { useState } from "react"

import type { Grounding, Verification } from "@/lib/types"
import { cn } from "@/lib/utils"

/**
 * How far the answer above can be trusted.
 *
 * Three signals, all produced by the backend and none of them editing the
 * answer itself — the last time this codebase post-processed model output it
 * regex-stripped real results out of it. Shown together because they answer one
 * question: is this number safe to act on?
 *
 * Deliberately quiet when everything is fine. A verification badge that appears
 * on every answer is decoration; one that appears next to a mismatch is a
 * warning someone will actually read.
 */
export function AnswerTrust({
  verification,
  grounding,
  assumptions,
  findings,
  tier,
  iterations,
}: {
  verification?: Verification | null
  grounding?: Grounding | null
  assumptions: string[]
  findings: string[]
  tier?: string
  iterations?: number
}) {
  const mismatch = verification?.status === "mismatch"
  const ungrounded = grounding && !grounding.ok ? grounding.ungrounded : []
  const nothingToShow =
    !mismatch && ungrounded.length === 0 && assumptions.length === 0 && findings.length === 0
  if (nothingToShow) return null

  return (
    <div className="space-y-2">
      {mismatch && (
        <Callout tone="danger" icon={ShieldAlert} title="Verification disagreed with this result">
          <p>
            The analysis was recomputed by a different route and produced a different number. Treat the
            answer above as unreliable until you have checked the code.
          </p>
          {verification?.detail && (
            <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-destructive/5 p-2 font-mono text-[11px]">
              {verification.detail}
            </pre>
          )}
        </Callout>
      )}

      {ungrounded.length > 0 && (
        <Callout tone="warning" icon={AlertTriangle} title="Some figures were not computed">
          <p>
            These appear in the answer but in no execution output, so they were written rather than
            calculated:{" "}
            <span className="font-mono">{ungrounded.slice(0, 8).join(", ")}</span>
            {ungrounded.length > 8 && ` and ${ungrounded.length - 8} more`}.
          </p>
        </Callout>
      )}

      {findings.length > 0 && <Collapsible title="What the investigation established" items={findings} icon={Info} />}

      {assumptions.length > 0 && (
        <Collapsible
          title="Assumptions this result depends on"
          items={assumptions}
          icon={HelpCircle}
          hint="Read from the code that ran, not from the model's description of it."
        />
      )}

      {verification?.status === "verified" && (
        <p className="flex items-center gap-1.5 text-[11.5px] text-success">
          <BadgeCheck className="h-3.5 w-3.5" />
          Independently recomputed and matched
          {tier && iterations ? ` · ${iterations} steps at ${tier} depth` : ""}
        </p>
      )}
    </div>
  )
}

function Callout({
  tone,
  icon: Icon,
  title,
  children,
}: {
  tone: "danger" | "warning"
  icon: typeof AlertTriangle
  title: string
  children: React.ReactNode
}) {
  return (
    <div
      className={cn(
        "rounded-xl border p-3.5 text-[12.5px] leading-relaxed",
        tone === "danger" && "border-destructive/25 bg-destructive/5 text-destructive",
        tone === "warning" && "border-warning/25 bg-warning/8 text-warning",
      )}
    >
      <p className="flex items-center gap-2 font-medium">
        <Icon className="h-4 w-4 shrink-0" />
        {title}
      </p>
      <div className="mt-1.5 pl-6">{children}</div>
    </div>
  )
}

function Collapsible({
  title,
  items,
  icon: Icon,
  hint,
}: {
  title: string
  items: string[]
  icon: typeof Info
  hint?: string
}) {
  const [open, setOpen] = useState(false)

  return (
    <div className="rounded-xl border border-border bg-card">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left text-[12.5px] font-medium transition-colors duration-[var(--duration-fast)] hover:bg-muted/50"
      >
        <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        {title}
        <span className="ml-auto font-mono text-[10.5px] text-muted-foreground">{items.length}</span>
      </button>
      {open && (
        <div className="border-t border-border px-3.5 py-3">
          {hint && <p className="mb-2 text-[11.5px] italic text-muted-foreground">{hint}</p>}
          <ul className="space-y-1.5">
            {items.map((item, index) => (
              <li key={index} className="flex gap-2 text-[12.5px] leading-relaxed text-muted-foreground">
                <span aria-hidden className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-muted-foreground/50" />
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
