"use client"

import { ArrowUp, Loader2, Paperclip, Square, Zap } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"

import { cn } from "@/lib/utils"

interface ComposerProps {
  onSend: (content: string, mode: "planning" | "fast") => void
  onStop: () => void
  onUpload: (file: File) => void
  isRunning: boolean
  isUploading: boolean
  hasData: boolean
  disabled?: boolean
  acceptedFormats: string[]
  mode: "planning" | "fast"
  onModeChange: (mode: "planning" | "fast") => void
}

const MAX_HEIGHT = 200

export function Composer({
  onSend,
  onStop,
  onUpload,
  isRunning,
  isUploading,
  hasData,
  disabled,
  acceptedFormats,
  mode,
  onModeChange,
}: ComposerProps) {
  const [value, setValue] = useState("")
  const [dragging, setDragging] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const autoResize = useCallback(() => {
    const node = textareaRef.current
    if (!node) return
    node.style.height = "auto"
    node.style.height = `${Math.min(node.scrollHeight, MAX_HEIGHT)}px`
  }, [])

  useEffect(autoResize, [value, autoResize])

  const submit = useCallback(() => {
    const trimmed = value.trim()
    if (!trimmed || isRunning || disabled) return
    onSend(trimmed, mode)
    setValue("")
    requestAnimationFrame(autoResize)
  }, [autoResize, disabled, isRunning, mode, onSend, value])

  const handleFiles = useCallback(
    (files: FileList | null) => {
      const file = files?.[0]
      if (file) onUpload(file)
    },
    [onUpload],
  )

  const accept = acceptedFormats.map((extension) => `.${extension.replace(/^\./, "")}`).join(",")

  return (
    <div className="px-4 pb-4">
      <div
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          handleFiles(event.dataTransfer.files)
        }}
        className={cn(
          "mx-auto w-full max-w-3xl rounded-2xl border bg-card shadow-sm transition-colors",
          dragging ? "border-primary bg-primary/5" : "border-border",
        )}
      >
        <div className="flex items-end gap-2 px-3 pt-3">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault()
                submit()
              }
            }}
            rows={1}
            disabled={disabled}
            placeholder={
              hasData
                ? "Ask anything about your data…"
                : `Drop a file or click the clip to begin (${acceptedFormats.slice(0, 4).join(", ")}…)`
            }
            aria-label="Message"
            className="max-h-[200px] flex-1 resize-none bg-transparent py-1.5 text-[15px] leading-6 placeholder:text-muted-foreground focus:outline-none disabled:opacity-50"
          />

          {isRunning ? (
            <button
              type="button"
              onClick={onStop}
              aria-label="Stop generating"
              className="mb-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-foreground text-background transition-transform hover:scale-105"
            >
              <Square className="h-3 w-3" fill="currentColor" />
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={!value.trim() || disabled}
              aria-label="Send message"
              className={cn(
                "mb-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-all",
                value.trim() && !disabled
                  ? "bg-foreground text-background hover:scale-105"
                  : "cursor-not-allowed bg-muted text-muted-foreground",
              )}
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          )}
        </div>

        <div className="flex items-center justify-between px-3 pb-2.5 pt-1.5">
          <div className="flex items-center gap-1">
            <input
              ref={fileInputRef}
              type="file"
              accept={accept}
              onChange={(event) => {
                handleFiles(event.target.files)
                event.target.value = ""
              }}
              className="hidden"
              aria-label="Upload a dataset"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isUploading || disabled}
              aria-label="Attach a dataset"
              className="flex h-7 w-7 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
            >
              {isUploading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Paperclip className="h-3.5 w-3.5" />
              )}
            </button>
          </div>

          <button
            type="button"
            onClick={() => onModeChange(mode === "planning" ? "fast" : "planning")}
            title={
              mode === "planning"
                ? "Planning mode: review the plan before it runs"
                : "Fast mode: execute immediately"
            }
            className={cn(
              "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
              mode === "planning"
                ? "bg-indigo-500/10 text-indigo-600 hover:bg-indigo-500/20 dark:text-indigo-400"
                : "bg-emerald-500/10 text-emerald-600 hover:bg-emerald-500/20 dark:text-emerald-400",
            )}
          >
            <Zap className="h-3 w-3" />
            {mode === "planning" ? "Plan first" : "Fast"}
          </button>
        </div>
      </div>

      <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-muted-foreground">
        Generated code runs in an isolated sandbox. Verify results before relying on them.
      </p>
    </div>
  )
}
