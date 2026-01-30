"use client"

import { useEffect, useRef, useState } from "react"
import { MessageBubble } from "./message-bubble"
import type { Message } from "./chat-shell"
import { TypingIndicator } from "./typing-indicator"
import { AlertCircle, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { AnimatedOrb } from "./animated-orb"

interface MessageListProps {
  messages: Message[]
  isStreaming: boolean
  error: string | null
  onRetry: () => void
  isLoaded: boolean // Added isLoaded prop to know when localStorage is loaded
}

export function MessageList({ messages, isStreaming, error, onRetry, isLoaded }: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const rafRef = useRef<number | null>(null)
  const [hasAnimated, setHasAnimated] = useState(false)
  const lastScrollRef = useRef<number>(0)
  const hasPlayedIntroRef = useRef(false) // Track if intro has played

  useEffect(() => {
    if (!isLoaded) return // Wait for localStorage to load

    // Only animate if no messages were loaded (fresh start)
    if (messages.length === 0 && !hasPlayedIntroRef.current) {
      setHasAnimated(true)
      hasPlayedIntroRef.current = true
    } else if (messages.length > 0) {
      // Skip animation if messages exist
      setHasAnimated(false)
      hasPlayedIntroRef.current = true
    }
  }, [isLoaded, messages.length])

  useEffect(() => {
    if (!containerRef.current) return
    // Immediate scroll to bottom when messages change
    const container = containerRef.current
    container.scrollTop = container.scrollHeight
    setAutoScroll(true)
  }, [messages.length])

  useEffect(() => {
    if (!isStreaming || !autoScroll || !containerRef.current) {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      return
    }

    const container = containerRef.current
    lastScrollRef.current = container.scrollTop

    const smoothScroll = () => {
      if (!container) return

      const { scrollHeight, clientHeight } = container
      const targetScroll = scrollHeight - clientHeight
      const currentScroll = lastScrollRef.current
      const diff = targetScroll - currentScroll

      if (diff > 0.5) {
        const newScroll = currentScroll + diff * 0.03
        lastScrollRef.current = newScroll
        container.scrollTop = newScroll
      }

      rafRef.current = requestAnimationFrame(smoothScroll)
    }

    // Start immediately
    rafRef.current = requestAnimationFrame(smoothScroll)

    return () => {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
    }
  }, [isStreaming, autoScroll])

  // Detect if user scrolls up to disable auto-scroll
  const handleScroll = () => {
    if (!containerRef.current || isStreaming) return

    const { scrollTop, scrollHeight, clientHeight } = containerRef.current
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 150
    setAutoScroll(isAtBottom)
  }

  const lastMessage = messages[messages.length - 1]
  const showTypingIndicator =
    isStreaming &&
    (messages.length === 0 ||
      lastMessage?.role === "user" ||
      (lastMessage?.role === "assistant" && lastMessage?.content === ""))

  if (!isLoaded) {
    return (
      <div className="absolute inset-0 flex items-center justify-center">
        <AnimatedOrb size={64} />
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      className="absolute inset-0 overflow-y-auto pt-16 pb-32 space-y-4 border-none px-6"
      role="log"
      aria-label="Chat messages"
      aria-live="polite"
    >
      {/* Empty state */}
      {messages.length === 0 && !error && !isStreaming && (
        <div className="flex flex-col items-center justify-center h-full text-center text-stone-400">
          <div className={`mb-4 ${hasAnimated ? "orb-intro" : ""}`}>
            <AnimatedOrb size={128} />
          </div>
          <p className={`text-lg font-medium text-gray-500 ${hasAnimated ? "text-blur-intro" : ""}`}>
            Hi, my name is Wizard
          </p>
          <p className={`text-sm mt-1 text-gray-400 ${hasAnimated ? "text-blur-intro-delay" : ""}`}>
            Send a message to begin chatting with the AI assistant
          </p>
        </div>
      )}

      {/* Messages */}
      {messages
        .filter((message) => {
          // Hide empty assistant messages during streaming - they'll be shown as typing indicator instead
          if (isStreaming && message.role === "assistant" && message === lastMessage && message.content === "") {
            return false
          }
          return true
        })
        .map((message) => (
          <MessageBubble
            key={message.id}
            message={message}
            isStreaming={isStreaming && message.role === "assistant" && message === lastMessage}
          />
        ))}

      {showTypingIndicator && <TypingIndicator />}

      {/* Error state */}
      {error && (
        <div
          className="flex items-center gap-3 p-4 bg-red-50 border border-red-200 rounded-xl"
          role="alert"
          style={{
            boxShadow:
              "rgba(14, 63, 126, 0.04) 0px 0px 0px 1px, rgba(42, 51, 69, 0.04) 0px 1px 1px -0.5px, rgba(42, 51, 70, 0.04) 0px 3px 3px -1.5px, rgba(42, 51, 70, 0.04) 0px 6px 6px -3px, rgba(14, 63, 126, 0.04) 0px 12px 12px -6px, rgba(14, 63, 126, 0.04) 0px 24px 24px -12px",
          }}
        >
          <AlertCircle className="w-5 h-5 text-red-500 shrink-0" aria-hidden="true" />
          <div className="flex-1">
            <p className="text-sm font-medium text-red-800">Something went wrong</p>
            <p className="text-xs text-red-600 mt-0.5">{error}</p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={onRetry}
            className="text-red-600 hover:text-red-700 hover:bg-red-100 transition-colors"
            aria-label="Retry sending message"
          >
            <RefreshCw className="w-4 h-4 mr-1" aria-hidden="true" />
            Retry
          </Button>
        </div>
      )}

      {/* Scroll anchor */}
      <div ref={bottomRef} aria-hidden="true" className="h-20" />
    </div>
  )
}
