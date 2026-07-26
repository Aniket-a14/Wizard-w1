"use client"

import { AlertTriangle, BarChart3, Check, Copy, Download, TriangleAlert } from "lucide-react"
import { useState } from "react"

import { AnimatedOrb } from "@/components/animated-orb"
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
      className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-muted-foreground transition-colors duration-[var(--duration-fast)] hover:bg-muted hover:text-foreground"
      aria-label="Copy message"
    >
      {copied ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3" />}
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
      <div className="reveal-in flex justify-end px-4 py-2.5">
        <div className="max-w-[80%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-[14.5px] leading-relaxed text-primary-foreground shadow-sm">
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
        {/* The orb doubles as the assistant avatar and as the "working" indicator:
            it is always in motion, so a static frame never looks stalled. */}
        <div className="mt-0.5">
          <AnimatedOrb size={26} />
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
            <div className="mb-3 rounded-xl border border-border bg-card p-3.5 shadow-xs">
              <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.14em] text-brand">
                Proposed plan
              </p>
              <MarkdownRenderer content={message.plan} />
            </div>
          )}

          {waitingForFirstToken && (
            <div className="flex items-center gap-2 py-1" role="status" aria-label="Working">
              <span className="flex items-center gap-1">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand/60 [animation-delay:0ms]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand/60 [animation-delay:150ms]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand/60 [animation-delay:300ms]" />
              </span>
              {message.statusLabel && (
                <span className="text-[12.5px] text-muted-foreground">{message.statusLabel}</span>
              )}
            </div>
          )}

          {message.content && (
            <div className="text-[15px] leading-7">
              <MarkdownRenderer content={message.content} />
              {/* Marks where the stream has reached. The text itself arrives token
                  by token from the socket — this is not a reveal animation. */}
              {showCursor && <span className="caret" aria-hidden="true" />}
            </div>
          )}

          {message.artifacts.some((artifact) => artifact.kind.startsWith("plot")) && (
            <button
              type="button"
              onClick={() => {
                const plot = message.artifacts.find((artifact) => artifact.kind.startsWith("plot"))
                if (plot) onOpenArtifact(plot)
              }}
              className="lift mt-3 inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-[12.5px] font-medium shadow-xs hover:border-brand/40"
            >
              <BarChart3 className="h-3.5 w-3.5 text-brand" />
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
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1.5 text-[12px] shadow-xs transition-colors duration-[var(--duration-fast)] hover:border-brand/40 hover:bg-accent"
                >
                  <Download className="h-3 w-3 text-muted-foreground" />
                  {file}
                </a>
              ))}
            </div>
          )}

          {message.warnings.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {message.warnings.map((warning, index) => (
                <li
                  key={`${index}-${warning.slice(0, 24)}`}
                  className="flex items-start gap-2 text-[12.5px] leading-relaxed text-warning"
                >
                  <TriangleAlert className="mt-0.5 h-3 w-3 shrink-0" />
                  <span>{warning}</span>
                </li>
              ))}
            </ul>
          )}

          {message.error && (
            <div className="mt-3 flex items-start gap-2.5 rounded-xl border border-destructive/25 bg-destructive/8 p-3.5 text-[13.5px] leading-relaxed text-destructive">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{message.error}</span>
            </div>
          )}

          {message.approval && (
            <div className="ring-gradient mt-3 rounded-xl p-4 shadow-sm">
              <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.14em] text-brand">
                Waiting on you
              </p>
              <p className="mb-3.5 text-[14px] leading-relaxed">{message.approval.prompt}</p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => onApprove(message, true)}
                  className="rounded-lg bg-[linear-gradient(120deg,var(--brand),var(--brand-2))] px-3.5 py-2 text-[12.5px] font-medium text-brand-foreground shadow-brand transition-all duration-[var(--duration-fast)] hover:brightness-105 active:scale-[0.985]"
                >
                  {message.approval.tool === "web_search" ? "Allow search" : "Run it"}
                </button>
                <button
                  type="button"
                  onClick={() => onApprove(message, false)}
                  className="rounded-lg border border-border px-3.5 py-2 text-[12.5px] font-medium transition-colors duration-[var(--duration-fast)] hover:bg-muted"
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
