"use client"

import { ChevronRight, Brain } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { cn } from "@/lib/utils"

interface ReasoningPanelProps {
  content: string
  streaming: boolean
  /** Seconds spent reasoning, shown once the panel collapses. */
  elapsedMs?: number
}

/**
 * Collapsible "thinking" panel, in the shape ChatGPT and Gemini use: expanded
 * and auto-scrolling while tokens arrive, collapsed to a one-line summary once
 * the model moves on.
 */
export function ReasoningPanel({ content, streaming, elapsedMs }: ReasoningPanelProps) {
  // `null` means "follow the stream": expanded while tokens arrive, collapsed
  // once they stop. Once the reader clicks, their choice wins. Deriving this
  // rather than syncing it in an effect avoids a cascading re-render.
  const [override, setOverride] = useState<boolean | null>(null)
  const open = override ?? streaming
  const bodyRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (open && streaming && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight
    }
  }, [content, open, streaming])

  if (!content.trim()) return null

  const seconds = elapsedMs ? Math.max(1, Math.round(elapsedMs / 1000)) : null

  return (
    <div className="mb-3 overflow-hidden rounded-xl border border-border/60 bg-muted/40">
      <button
        type="button"
        onClick={() => setOverride(!open)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
        aria-expanded={open}
      >
        <Brain className={cn("h-3.5 w-3.5 shrink-0", streaming && "animate-pulse text-indigo-500")} />
        <span>
          {streaming ? "Thinking…" : seconds ? `Thought for ${seconds}s` : "Reasoning"}
        </span>
        <ChevronRight
          className={cn("ml-auto h-3.5 w-3.5 transition-transform duration-200", open && "rotate-90")}
        />
      </button>

      {open && (
        <div
          ref={bodyRef}
          className="max-h-64 overflow-y-auto border-t border-border/60 px-3 py-2.5 text-[13px] leading-relaxed text-muted-foreground"
        >
          <p className="whitespace-pre-wrap break-words">{content}</p>
          {streaming && (
            <span className="ml-0.5 inline-block h-3.5 w-[2px] animate-pulse bg-indigo-500 align-text-bottom" />
          )}
        </div>
      )}
    </div>
  )
}
