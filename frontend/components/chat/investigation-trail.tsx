"use client"

import {
  BookOpen,
  Check,
  ChevronRight,
  CircleDot,
  Code2,
  Flag,
  Loader2,
  RefreshCcw,
  Search,
  Split,
  Table2,
  X,
} from "lucide-react"
import { useState } from "react"

import type { ActionKind, SubagentBranch, TrailEntry } from "@/lib/types"
import { cn } from "@/lib/utils"

/**
 * What the agent did, move by move.
 *
 * A multi-step answer is only worth trusting if you can see how it was reached.
 * The old step timeline described a fixed pipeline — plan, generate, execute —
 * which is no longer what happens: the agent chooses each next move from real
 * output, and the interesting information is *which* move it chose and what it
 * found. Collapsed by default; the answer is the headline, this is the evidence.
 */

const ACTION_META: Record<ActionKind, { label: string; icon: typeof Code2; tone: string }> = {
  inspect: { label: "Examined the data", icon: Table2, tone: "text-brand" },
  code: { label: "Ran analysis", icon: Code2, tone: "text-foreground" },
  consult: { label: "Consulted references", icon: BookOpen, tone: "text-brand" },
  search: { label: "Searched the web", icon: Search, tone: "text-brand" },
  reflect: { label: "Revised the plan", icon: RefreshCcw, tone: "text-warning" },
  parallel: { label: "Investigated in parallel", icon: Split, tone: "text-brand" },
  answer: { label: "Concluded", icon: Flag, tone: "text-success" },
}

export function InvestigationTrail({
  trail,
  iteration,
  budget,
  streaming,
  subagents,
}: {
  trail: TrailEntry[]
  iteration?: number
  budget?: number
  streaming?: boolean
  /** Isolated branches a `parallel` entry fanned out to, keyed by branch id —
   *  see `TrailRow`, which matches them to their entry by `group`. */
  subagents?: Record<string, SubagentBranch>
}) {
  const [open, setOpen] = useState(false)

  if (trail.length === 0) return null

  const failures = trail.filter((entry) => entry.ok === false).length
  const revisions = trail.filter((entry) => entry.kind === "reflect").length

  return (
    <div className="ring-gradient overflow-hidden rounded-xl">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left transition-colors duration-[var(--duration-fast)] hover:bg-muted/50"
      >
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted-foreground",
            "transition-transform duration-[var(--duration-base)] ease-[var(--ease-out-expo)]",
            open && "rotate-90",
          )}
        />
        <span className="text-[12.5px] font-medium">
          {trail.length} {trail.length === 1 ? "step" : "steps"}
        </span>

        {/* The budget is on the wire so progress can be shown against it —
            "step 4" means nothing without knowing what the ceiling was. */}
        {typeof budget === "number" && budget > 1 && (
          <span className="font-mono text-[10.5px] text-muted-foreground">
            {iteration ?? trail.length}/{budget}
          </span>
        )}

        <span className="ml-auto flex items-center gap-2 text-[11px] text-muted-foreground">
          {revisions > 0 && <span className="text-warning">{revisions} revised</span>}
          {failures > 0 && <span>{failures} failed</span>}
          {streaming && <Loader2 className="h-3 w-3 animate-spin" />}
        </span>
      </button>

      {open && (
        <ol className="space-y-0 border-t border-border">
          {trail.map((entry, index) => (
            <TrailRow key={entry.id} entry={entry} index={index + 1} subagents={subagents} />
          ))}
        </ol>
      )}
    </div>
  )
}

function TrailRow({
  entry,
  index,
  subagents,
}: {
  entry: TrailEntry
  index: number
  subagents?: Record<string, SubagentBranch>
}) {
  const [expanded, setExpanded] = useState(false)
  const meta = ACTION_META[entry.kind] ?? ACTION_META.code
  const Icon = meta.icon
  const branches =
    entry.kind === "parallel" && entry.group
      ? Object.values(subagents ?? {}).filter((branch) => branch.group === entry.group)
      : []
  const pending = entry.observation === undefined && branches.length === 0
  const hasDetail = Boolean(entry.observation) || branches.length > 0

  return (
    <li className="border-b border-border last:border-b-0">
      <button
        type="button"
        onClick={() => hasDetail && setExpanded((value) => !value)}
        disabled={!hasDetail}
        className={cn(
          "flex w-full items-start gap-3 px-3.5 py-2.5 text-left",
          "transition-colors duration-[var(--duration-fast)]",
          hasDetail && "hover:bg-muted/40",
          !hasDetail && "cursor-default",
        )}
      >
        <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
          {pending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
          ) : entry.ok === false ? (
            <X className="h-3.5 w-3.5 text-destructive" />
          ) : entry.kind === "answer" ? (
            <Check className="h-3.5 w-3.5 text-success" />
          ) : (
            <Icon className={cn("h-3.5 w-3.5", meta.tone)} />
          )}
        </span>

        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-mono text-[10px] text-muted-foreground">{index}</span>
            <span className="text-[12.5px] font-medium">{meta.label}</span>
            {/* A guessed action is not the same as a chosen one, and a run full
                of guesses means the model is too small for the loop. */}
            {entry.inferred && (
              <span className="rounded px-1 py-px text-[9.5px] text-muted-foreground ring-1 ring-border">
                inferred
              </span>
            )}
          </span>
          {entry.goal && (
            <span className="mt-0.5 block truncate text-[12px] text-muted-foreground">{entry.goal}</span>
          )}
          {entry.rationale && (
            <span className="mt-0.5 block truncate text-[11.5px] italic text-muted-foreground">
              {entry.rationale}
            </span>
          )}
        </span>

        {hasDetail && (
          <ChevronRight
            className={cn(
              "mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground",
              "transition-transform duration-[var(--duration-base)] ease-[var(--ease-out-expo)]",
              expanded && "rotate-90",
            )}
          />
        )}
      </button>

      {expanded && branches.length > 0 && (
        <div className="space-y-2 px-3.5 pb-3">
          {branches.map((branch) => (
            <SubagentBranchPanel key={branch.id} branch={branch} />
          ))}
        </div>
      )}

      {expanded && branches.length === 0 && entry.observation && (
        <div className="px-3.5 pb-3">
          <pre className="max-h-72 overflow-auto rounded-lg bg-muted/60 p-3 font-mono text-[11.5px] leading-relaxed">
            {entry.observation}
          </pre>
          {entry.truncated && (
            <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <CircleDot className="h-3 w-3" />
              Showing part of {entry.chars?.toLocaleString()} characters.
            </p>
          )}
        </div>
      )}
    </li>
  )
}

/**
 * One isolated branch, rendered as its own miniature trail.
 *
 * Distinguishable as a *parallel* branch rather than interleaved with the
 * main thread — that's the whole point of the panel, not just a nicety: two
 * branches ran concurrently, and showing their steps in one flat list would
 * read as if one thread produced them in that order.
 */
function SubagentBranchPanel({ branch }: { branch: SubagentBranch }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="ring-gradient overflow-hidden rounded-lg">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors duration-[var(--duration-fast)] hover:bg-muted/50"
      >
        <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center">
          {!branch.done ? (
            <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
          ) : branch.ok ? (
            <Check className="h-3 w-3 text-success" />
          ) : (
            <X className="h-3 w-3 text-destructive" />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[12px] font-medium">{branch.goal || branch.id}</span>
        </span>
        {typeof branch.costUsd === "number" && (
          <span className="font-mono text-[10px] text-muted-foreground">${branch.costUsd.toFixed(4)}</span>
        )}
        {branch.trail.length > 0 && (
          <ChevronRight
            className={cn(
              "h-3 w-3 shrink-0 text-muted-foreground",
              "transition-transform duration-[var(--duration-base)] ease-[var(--ease-out-expo)]",
              expanded && "rotate-90",
            )}
          />
        )}
      </button>

      {expanded && branch.trail.length > 0 && (
        <ol className="space-y-0 border-t border-border">
          {branch.trail.map((entry, index) => (
            <TrailRow key={entry.id} entry={entry} index={index + 1} />
          ))}
        </ol>
      )}
    </div>
  )
}
