"use client"

import {
  AlertTriangle,
  BarChart3,
  Check,
  Copy,
  Download,
  Sparkles,
  TriangleAlert,
} from "lucide-react"
import { useState } from "react"

import { MarkdownRenderer } from "@/components/markdown-renderer"
import { ReasoningPanel } from "@/components/chat/reasoning-panel"
import { StepTimeline } from "@/components/chat/step-timeline"
import { workspaceFileUrl } from "@/lib/api"
import type { Artifact, ChatMessage } from "@/lib/types"
import { cn } from "@/lib/utils"

interface MessageProps {
  message: ChatMessage
  onApprove: (message: ChatMessage, approved: boolean) => void
  onOpenArtifact: (artifact: Artifact) => void
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard.writeText(value).then(() => {
          setCopied(true)
          setTimeout(() => setCopied(false), 1600)
        })
      }}
      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      aria-label="Copy message"
    >
      {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
      {copied ? "Copied" : "Copy"}
    </button>
  )
}

/**
 * One conversation turn.
 *
 * User turns are a right-aligned bubble; assistant turns are full-width prose,
 * matching ChatGPT/Gemini. Reasoning, tool steps and artifacts are secondary
 * surfaces around the answer rather than concatenated into it.
 */
export function Message({ message, onApprove, onOpenArtifact }: MessageProps) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end px-4 py-2">
        <div className="max-w-[80%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-sm leading-relaxed text-primary-foreground shadow-sm">
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
        </div>
      </div>
    )
  }

  const showCursor = message.streaming && message.content.length > 0
  const waitingForFirstToken = message.streaming && !message.content && !message.reasoning

  return (
    <div className="group px-4 py-3">
      <div className="flex gap-3">
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-sm">
          <Sparkles className="h-3.5 w-3.5" />
        </div>

        <div className="min-w-0 flex-1">
          {message.reasoning && (
            <ReasoningPanel
              content={message.reasoning}
              streaming={Boolean(message.streaming) && !message.content}
              elapsedMs={message.elapsedMs}
            />
          )}

          <StepTimeline steps={message.steps} code={message.code} stdout={message.stdout} />

          {message.plan && !message.content && (
            <div className="mb-3 rounded-xl border border-border/60 bg-card p-3">
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Proposed plan
              </p>
              <MarkdownRenderer content={message.plan} />
            </div>
          )}

          {waitingForFirstToken && (
            <div className="flex items-center gap-1.5 py-1" role="status" aria-label="Working">
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/50 [animation-delay:0ms]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/50 [animation-delay:150ms]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/50 [animation-delay:300ms]" />
              {message.statusLabel && (
                <span className="ml-2 text-xs text-muted-foreground">{message.statusLabel}</span>
              )}
            </div>
          )}

          {message.content && (
            <div className="text-[15px] leading-7">
              <MarkdownRenderer content={message.content} />
              {showCursor && (
                <span className="ml-0.5 inline-block h-4 w-[2px] animate-pulse bg-foreground align-text-bottom" />
              )}
            </div>
          )}

          {message.artifacts.some((artifact) => artifact.kind.startsWith("plot")) && (
            <button
              type="button"
              onClick={() => {
                const plot = message.artifacts.find((artifact) => artifact.kind.startsWith("plot"))
                if (plot) onOpenArtifact(plot)
              }}
              className="mt-3 inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-xs font-medium transition-colors hover:bg-muted"
            >
              <BarChart3 className="h-3.5 w-3.5 text-emerald-600" />
              View chart
            </button>
          )}

          {message.downloads.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {message.downloads.map((file) => (
                <a
                  key={file}
                  href={workspaceFileUrl(file)}
                  download={file}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs transition-colors hover:bg-muted"
                >
                  <Download className="h-3 w-3 text-muted-foreground" />
                  {file}
                </a>
              ))}
            </div>
          )}

          {message.warnings.length > 0 && (
            <ul className="mt-3 space-y-1">
              {message.warnings.map((warning, index) => (
                <li
                  key={`${index}-${warning.slice(0, 24)}`}
                  className="flex items-start gap-1.5 text-xs text-amber-600 dark:text-amber-400"
                >
                  <TriangleAlert className="mt-0.5 h-3 w-3 shrink-0" />
                  <span>{warning}</span>
                </li>
              ))}
            </ul>
          )}

          {message.error && (
            <div className="mt-3 flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-700 dark:text-rose-300">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{message.error}</span>
            </div>
          )}

          {message.approval && (
            <div className="mt-3 rounded-xl border border-indigo-500/30 bg-indigo-500/5 p-3">
              <p className="mb-2.5 text-sm">{message.approval.prompt}</p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => onApprove(message, true)}
                  className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90"
                >
                  {message.approval.tool === "web_search" ? "Allow search" : "Run it"}
                </button>
                <button
                  type="button"
                  onClick={() => onApprove(message, false)}
                  className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {!message.streaming && message.content && (
            <div
              className={cn(
                "mt-1.5 flex items-center gap-1 opacity-0 transition-opacity",
                "group-hover:opacity-100 focus-within:opacity-100",
              )}
            >
              <CopyButton value={message.content} />
              {message.elapsedMs ? (
                <span className="text-[11px] text-muted-foreground/60">
                  {(message.elapsedMs / 1000).toFixed(1)}s
                </span>
              ) : null}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
