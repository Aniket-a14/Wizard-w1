"use client"

import { cn } from "@/lib/utils"
import type { Message } from "./chat-shell"
import { User, ChevronDown, Brain } from "lucide-react"
import { MarkdownRenderer } from "./markdown-renderer"
import Image from "next/image"
import { AnimatedOrb } from "./animated-orb"
import { useState } from "react"

interface MessageBubbleProps {
  message: Message
  isStreaming?: boolean
}

// Format time for display
function formatTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
}

export function MessageBubble({ message, isStreaming = false }: MessageBubbleProps) {
  const isUser = message.role === "user"
  const hasActions = message.actions && message.actions.length > 0
  const [thoughtOpen, setThoughtOpen] = useState(hasActions)

  // During streaming or when approval is active, keep thoughts expanded by default
  const isThoughtVisible = isStreaming || hasActions || thoughtOpen

  return (
    <div
      className={cn(
        "flex max-w-[90%] md:max-w-[80%] gap-2",
        isUser
          ? "ml-auto flex-row-reverse user-message-enter"
          : "mr-auto animate-in fade-in slide-in-from-bottom-2 duration-300 items-end",
      )}
    >
      {/* Avatar */}
      <div
        className={cn(
          "w-7 h-7 rounded-full flex items-center justify-center shrink-0",
          isUser ? "bg-white" : "bg-emerald-600",
          !isUser && isStreaming && "sticky bottom-4 self-end transition-all duration-300",
        )}
        style={{
          boxShadow:
            "rgba(14, 63, 126, 0.04) 0px 0px 0px 1px, rgba(42, 51, 69, 0.04) 0px 1px 1px -0.5px, rgba(42, 51, 70, 0.04) 0px 3px 3px -1.5px",
        }}
        aria-hidden="true"
      >
        {isUser ? <User className="w-3.5 h-3.5 text-stone-800" /> : <AnimatedOrb className="w-7 h-7 shrink-0" />}
      </div>

      {/* Message content */}
      <div className={cn("flex flex-col", isUser ? "items-end" : "items-start")}>
        {/* Bubble */}
        <div
          className={cn(
            "rounded-2xl border-none overflow-hidden",
            isUser
              ? "bg-white text-stone-800 border border-stone-200 rounded-br-md"
              : "bg-transparent text-stone-800 rounded-bl-md",
          )}
          style={{
            boxShadow: isUser
              ? "rgba(14, 63, 126, 0.04) 0px 0px 0px 1px, rgba(42, 51, 69, 0.04) 0px 1px 1px -0.5px, rgba(42, 51, 70, 0.04) 0px 3px 3px -1.5px"
              : "none",
            willChange: isStreaming ? "height" : "auto",
            transition: "all 0.4s cubic-bezier(0.4, 0, 0.2, 1)",
          }}
        >
          <div
            className={cn(isUser ? "px-4 py-2.5" : "py-1")}
            style={{
              transition: "max-height 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease",
            }}
          >
            {isUser ? (
              <div className="flex flex-col gap-2">
                {message.imageData && (
                  <div className="w-20 h-20 rounded-lg overflow-hidden border border-stone-200">
                    <Image
                      src={message.imageData || "/placeholder.svg"}
                      alt="Uploaded image"
                      width={80}
                      height={80}
                      className="w-full h-full object-cover"
                    />
                  </div>
                )}
                <p className="text-sm whitespace-pre-wrap break-words">{message.content}</p>
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                {/* Thought block — visible live during streaming, collapsible after */}
                {message.thought && (
                  <>
                    <button
                      onClick={() => !isStreaming && setThoughtOpen(!thoughtOpen)}
                      className={cn(
                        "flex items-center gap-1.5 text-[11px] transition-colors py-0.5",
                        isStreaming
                          ? "text-indigo-400 cursor-default"
                          : "text-stone-400 hover:text-stone-500 cursor-pointer"
                      )}
                    >
                      {isStreaming ? (
                        <Brain className="w-3 h-3 animate-pulse" />
                      ) : (
                        <ChevronDown className={cn("w-3 h-3 transition-transform duration-200", thoughtOpen && "rotate-180")} />
                      )}
                      <span className="font-medium">
                        {isStreaming ? "Thinking..." : "Thought process"}
                      </span>
                    </button>
                    {isThoughtVisible && (
                      <div
                        className={cn(
                          "text-[11px] italic border-l-2 pl-2.5 py-1 mb-1 leading-relaxed transition-all duration-300",
                          isStreaming
                            ? "text-indigo-400/80 border-indigo-300"
                            : "text-stone-400 border-stone-200"
                        )}
                      >
                        {message.thought}
                      </div>
                    )}
                  </>
                )}
                <MarkdownRenderer content={message.content || " "} isStreaming={isStreaming} />
                {/* Downloads card */}
                {message.downloads && message.downloads.length > 0 && (
                  <div className="flex flex-col gap-1.5 mt-2.5 pt-2.5 border-t border-stone-100/50 w-full">
                    <p className="text-[10px] uppercase tracking-wider text-stone-400 font-semibold">Generated Files</p>
                    <div className="flex flex-wrap gap-1.5">
                      {message.downloads.map((file) => (
                        <a
                          key={file}
                          href={`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/workspace/static/${file}`}
                          download={file}
                          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl bg-white border border-stone-200 hover:border-emerald-500 hover:bg-emerald-50/20 text-stone-700 hover:text-emerald-700 transition-all duration-150 text-xs shadow-xs font-medium"
                        >
                          <svg className="w-3.5 h-3.5 text-stone-400 group-hover:text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
                          </svg>
                          {file}
                        </a>
                      ))}
                    </div>
                  </div>
                )}
                {/* Action buttons (Allow/Reject etc.) */}
                {message.actions && (
                  <div className="flex gap-2 mt-2 pt-2 border-t border-stone-100">
                    {message.actions.map((action, idx) => (
                      <button
                        key={idx}
                        onClick={action.onClick}
                        className={cn(
                          "px-3 py-1.5 text-xs font-medium rounded-lg transition-colors",
                          action.variant === "primary"
                            ? "bg-emerald-600 text-white hover:bg-emerald-700 shadow-sm"
                            : "bg-stone-100 text-stone-600 hover:bg-stone-200"
                        )}
                      >
                        {action.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Timestamp */}
        <span className="text-[10px] text-stone-400 mt-1">{formatTime(message.createdAt)}</span>
      </div>
    </div>
  )
}
