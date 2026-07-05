"use client"

import type React from "react"

import { useState, useRef, useCallback, type KeyboardEvent, useEffect } from "react"
import { Square, Paperclip, ArrowUp } from "lucide-react"
import { cn } from "@/lib/utils"
import { AnimatedOrb } from "./animated-orb"

interface ComposerProps {
  onSend: (content: string, mode: "planning" | "fast") => void
  onStop: () => void
  isStreaming: boolean
  disabled?: boolean
  onUpload: (file: File) => void
  isReady: boolean
  mode: "planning" | "fast"
  setMode: (mode: "planning" | "fast") => void
}

export function Composer({ onSend, onStop, isStreaming, disabled, onUpload, isReady, mode, setMode }: ComposerProps) {
  const [value, setValue] = useState("")
  const [hasAnimated, setHasAnimated] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    // Trigger intro animation after mount
    const timer = setTimeout(() => setHasAnimated(true), 0)
    return () => clearTimeout(timer)
  }, [setHasAnimated])


  const handleInput = useCallback(() => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = "auto"
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`
    }
  }, [])

  const playClick = useCallback(() => {
    const audio = new Audio("/sound/click.mp3")
    audio.volume = 0.5
    audio.play().catch(() => { }) // Ignore errors if blocked
  }, [])

  const handleSend = useCallback(() => {
    if (!value.trim() || isStreaming || disabled) return

    playClick()
    onSend(value, mode)
    setValue("")
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto"
    }
  }, [value, isStreaming, disabled, onSend, playClick, mode])

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend],
  )

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (file) {
        if (file.name.endsWith(".csv")) {
          playClick()
          onUpload(file)
        } else {
          alert("Please upload a CSV file")
        }
      }
      e.target.value = ""
    },
    [onUpload, playClick],
  )

  const toggleMode = () => {
    setMode(mode === "planning" ? "fast" : "planning")
    playClick()
  }

  return (
    <div className={cn("shrink-0 px-3 pb-3 pt-1", hasAnimated && "composer-intro")}>
      <div
        className="composer-glass rounded-2xl transition-all duration-200 overflow-hidden"
      >
        {/* Textarea Row */}
        <div className="flex items-end gap-2 px-3 pt-3 pb-2">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => {
              setValue(e.target.value)
              handleInput()
            }}
            onKeyDown={handleKeyDown}
            placeholder={isReady ? "Ask anything about your data..." : "Upload a CSV to start analysis..."}
            disabled={isStreaming || disabled}
            rows={1}
            className={cn(
              "flex-1 resize-none bg-transparent px-1 py-1.5 text-sm text-stone-800 placeholder:text-stone-400",
              "focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed",
              "max-h-[120px] overflow-y-auto",
            )}
            aria-label="Message input"
          />

          {isStreaming ? (
            <button
              onClick={() => {
                onStop()
              }}
              className="relative h-8 w-8 shrink-0 transition-all rounded-full flex items-center justify-center cursor-pointer hover:scale-105"
              aria-label="Stop generating"
            >
              <AnimatedOrb size={32} variant="red" />
              <Square
                className="w-3.5 h-3.5 absolute drop-shadow-md text-red-700"
                fill="currentColor"
                aria-hidden="true"
              />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!value.trim() || disabled}
              className={cn(
                "h-8 w-8 shrink-0 transition-all rounded-full flex items-center justify-center",
                !value.trim() || disabled
                  ? "bg-stone-200 cursor-not-allowed"
                  : "bg-stone-900 cursor-pointer hover:bg-stone-800 hover:scale-105 shadow-sm",
              )}
              aria-label="Send message"
            >
              <ArrowUp className={cn("w-4 h-4", !value.trim() || disabled ? "text-stone-400" : "text-white")} />
            </button>
          )}
        </div>

        {/* Bottom Actions Row */}
        <div className="flex items-center justify-between px-3 pb-2.5">
          <div className="flex items-center gap-1.5">
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv"
              onChange={handleFileSelect}
              className="hidden"
              aria-label="Upload CSV"
            />

            <button
              onClick={() => {
                fileInputRef.current?.click()
              }}
              disabled={isStreaming || disabled}
              className="h-7 w-7 shrink-0 bg-stone-100 hover:bg-stone-200 text-stone-500 hover:text-stone-700 rounded-lg flex items-center justify-center transition-colors disabled:opacity-40"
              aria-label="Attach CSV"
            >
              <Paperclip className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Mode Toggle */}
          <button
            onClick={toggleMode}
            className={cn(
              "text-[11px] font-semibold px-2.5 py-1 rounded-full transition-all duration-200 flex items-center gap-1.5",
              mode === "planning"
                ? "bg-indigo-50 text-indigo-600 hover:bg-indigo-100"
                : "bg-emerald-50 text-emerald-600 hover:bg-emerald-100"
            )}
          >
            <span className={cn("w-1.5 h-1.5 rounded-full", mode === "planning" ? "bg-indigo-400" : "bg-emerald-400")}></span>
            {mode === "planning" ? "Planning" : "Fast"}
          </button>
        </div>
      </div>
    </div>
  )
}
