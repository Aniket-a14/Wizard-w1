"use client"

import { useState, useEffect, useCallback } from "react"
import { MessageSquareDashed, BookOpenText } from "lucide-react"
import { MessageList } from "./message-list"
import { Composer } from "./composer"
import { Button } from "@/components/ui/button"

// Data model for messages
export interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  createdAt: Date
  imageData?: string
  thought?: string
  actions?: {
    label: string
    onClick: () => void
    variant?: "primary" | "secondary"
  }[]
}

// localStorage key for persisting messages
const STORAGE_KEY = "chat-messages"

// Generates a unique ID for messages
function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substring(2, 9)}`
}

// API Base URL
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export function ChatShell() {
  const [messages, setMessages] = useState<Message[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isLoaded, setIsLoaded] = useState(false)
  const [isFileUploaded, setIsFileUploaded] = useState(false)
  const [mode, setMode] = useState<"planning" | "fast">("planning")

  // Load messages from sessionStorage on mount
  useEffect(() => {
    try {
      const stored = sessionStorage.getItem(STORAGE_KEY)
      if (stored) {
        const parsed = JSON.parse(stored)
        const messagesWithDates = parsed.map((msg: Message) => ({
          ...msg,
          createdAt: new Date(msg.createdAt),
        }))
        setMessages(messagesWithDates)
        if (messagesWithDates.length > 0) {
          setIsFileUploaded(true)
        }
      } else {
        // Allow empty state to show the intro Orb animation
        setMessages([])
      }
    } catch (e) {
      console.error("Failed to load from sessionStorage:", e)
    } finally {
      setIsLoaded(true)
    }
  }, [])

  // Persist messages to sessionStorage whenever they change
  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(messages))
    } catch (e) {
      console.error("Failed to save messages to sessionStorage:", e)
    }
  }, [messages])

  // Handle file upload
  const handleUpload = useCallback(async (file: File) => {
    setError(null)
    setIsStreaming(true)

    const formData = new FormData()
    formData.append("file", file)

    try {
      const response = await fetch(`${API_BASE_URL}/upload`, {
        method: "POST",
        body: formData,
      })

      if (!response.ok) {
        let errorMessage = "Upload failed"
        try {
          const errorData = await response.json()
          if (errorData.detail) {
            errorMessage = typeof errorData.detail === "string"
              ? errorData.detail
              : JSON.stringify(errorData.detail)
          }
        } catch {
          // Fallback to default message if JSON parse fails
        }
        throw new Error(errorMessage)
      }

      const data = await response.json()

      const successMessage: Message = {
        id: generateId(),
        role: "assistant",
        content: `Dataset **${data.filename}** loaded successfully!`,
        createdAt: new Date(),
      }

      const detailsMessage: Message = {
        id: generateId(),
        role: "assistant",
        content: `I have detected **${data.shape[0]}** rows and **${data.shape[1]}** columns.\n\n**Columns:** ${data.columns.join(", ")}`,
        createdAt: new Date(),
      }

      const semanticSummary = data.catalog?.columns
        ? "\n\n**Semantic Insights:**\n" + Object.entries(data.catalog.columns)
          .map(([col, meta]) => {
            const m = meta as { semantic_type: string; quality: { missing_percentage: number } }
            return `- **${col}**: ${m.semantic_type} (${m.quality.missing_percentage}% missing)`
          })
          .join("\n")
        : "";

      const summaryMessage: Message = {
        id: generateId(),
        role: "assistant",
        content: `**Data Summary:**\n${data.summary || "I have analyzed the schema."}${semanticSummary}\n\n**Cleaning Stage**: ${data.cleaning_result}`,
        createdAt: new Date(),
      }

      setMessages((prev) => [...prev, successMessage, detailsMessage, summaryMessage])
      setIsFileUploaded(true)
    } catch (e) {
      console.error("Error uploading file:", e)
      setError(e instanceof Error ? e.message : "An error occurred during upload")
      setIsFileUploaded(false)
    } finally {
      setIsStreaming(false)
    }
  }, [])

  // Send a message to the AI
  const sendMessage = useCallback(
    async (content: string, currentMode: "planning" | "fast" = "planning", isConfirmedPlan: boolean = false) => {
      if (!content.trim() || isStreaming || !isFileUploaded) return

      setError(null)

      const userMessage: Message = {
        id: generateId(),
        role: "user",
        content: content.trim(),
        createdAt: new Date(),
      }

      // Only add user message if it's NOT a confirmation of an existing plan (to avoid clutter)
      // Actually, typically we do want to show "Confirmed" or similar.
      // But for simplicity, we just add it.
      if (!isConfirmedPlan) {
        setMessages((prev) => [...prev, userMessage])
      }

      setIsStreaming(true)

      try {
        const response = await fetch(`${API_BASE_URL}/chat`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            message: content.trim(),
            mode: currentMode,
            is_confirmed_plan: isConfirmedPlan
          }),
        })

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`)
        }

        const data = await response.json()

        const responseMessage: Message = {
          id: generateId(),
          role: "assistant",
          content: data.response,
          thought: data.thought,
          createdAt: new Date(),
        }

        const newMessages = [responseMessage]

        if (data.code) {
          newMessages.push({
            id: generateId(),
            role: "assistant",
            content: `\`\`\`python\n${data.code}\n\`\`\``,
            createdAt: new Date(),
          })
        }

        // Attach image to the last message so it appears at the bottom
        if (data.image) {
          newMessages[newMessages.length - 1].imageData = data.image
        }

        // Handle Confirmation
        if (data.status === "waiting_confirmation") {
          const confirmMessage: Message = {
            id: generateId(),
            role: "assistant",
            content: "I have created a plan based on your request. Please review the logic above.",
            createdAt: new Date(),
            actions: [
              {
                label: "Confirm & Execute",
                variant: "primary",
                onClick: () => {
                  // Execute the plan
                  sendMessage(data.response, "fast", true)
                }
              },
              {
                label: "Cancel",
                variant: "secondary",
                onClick: () => {
                  setMessages(prev => prev.filter(m => m.id !== confirmMessage.id))
                }
              }
            ]
          }
          newMessages.push(confirmMessage)
        }

        setMessages((prev) => [...prev, ...newMessages])

      } catch (e) {
        console.error("Error sending message:", e)
        setError(e instanceof Error ? e.message : "An error occurred")
      } finally {
        setIsStreaming(false)
      }
    },
    [isStreaming, isFileUploaded, setMessages, setError, setIsStreaming],
  )

  // Generate Executive Story
  const generateReport = useCallback(async () => {
    if (isStreaming || !isFileUploaded) return
    setIsStreaming(true)
    setError(null)

    try {
      const response = await fetch(`${API_BASE_URL}/report`)
      if (!response.ok) throw new Error("Failed to generate report")

      const data = await response.json()

      const reportMessage: Message = {
        id: generateId(),
        role: "assistant",
        content: data.report,
        createdAt: new Date(),
      }

      setMessages((prev) => [...prev, reportMessage])
    } catch {
      console.error("Error generating report:")
      setError("Failed to generate executive story.")
    } finally {
      setIsStreaming(false)
    }
  }, [isStreaming, isFileUploaded, setMessages, setError, setIsStreaming])

  const retry = useCallback(() => {
    if (messages.length === 0) return
    const lastUserMessage = [...messages].reverse().find((m) => m.role === "user")
    if (lastUserMessage) {
      const index = messages.findIndex((m) => m.id === lastUserMessage.id)
      setMessages(messages.slice(0, index))
      setError(null)
      setTimeout(() => sendMessage(lastUserMessage.content), 100)
    }
  }, [messages, sendMessage, setMessages, setError])

  const playClick = useCallback(() => {
    const audio = new Audio("/sound/click.mp3")
    audio.volume = 0.5
    audio.play().catch(() => { })
  }, [])

  const stopStreaming = useCallback(() => {
    // Abort logic removed as we are not streaming anymore
  }, [])

  const clearChat = useCallback(() => {
    playClick()
    setMessages([])
    setError(null)
    setIsFileUploaded(false)
    sessionStorage.removeItem(STORAGE_KEY)
  }, [playClick])

  return (
    <div
      className="relative h-dvh bg-stone-50"
      style={{
        boxShadow:
          "rgba(14, 63, 126, 0.04) 0px 0px 0px 1px, rgba(42, 51, 69, 0.04) 0px 1px 1px -0.5px, rgba(42, 51, 70, 0.04) 0px 3px 3px -1.5px, rgba(42, 51, 70, 0.04) 0px 6px 6px -3px, rgba(14, 63, 126, 0.04) 0px 12px 12px -6px, rgba(14, 63, 126, 0.04) 0px 24px 24px -12px",
      }}
    >
      <Button
        onClick={clearChat}
        variant="ghost"
        size="icon"
        className="absolute top-4 left-4 z-20 h-10 w-10 rounded-full bg-zinc-100 hover:bg-zinc-200 text-stone-600"
        aria-label="Reset chat"
      >
        <MessageSquareDashed className="w-5 h-5" />
      </Button>

      <div className="absolute top-4 right-4 z-20 flex gap-2">
        <Button
          onClick={generateReport}
          disabled={!isFileUploaded || isStreaming}
          variant="outline"
          className="rounded-full bg-white/80 backdrop-blur-md border-stone-200 text-stone-600 hover:bg-white flex items-center gap-2 px-4 h-10 text-xs font-semibold shadow-sm"
        >
          <BookOpenText className="w-4 h-4 text-emerald-600" />
          Executive Story
        </Button>
      </div>

      <MessageList messages={messages} isStreaming={isStreaming} error={error} onRetry={retry} isLoaded={isLoaded} />

      <Composer
        onSend={sendMessage}
        onStop={stopStreaming}
        isStreaming={isStreaming}
        disabled={!!error}
        onUpload={handleUpload}
        isReady={isFileUploaded}
        mode={mode}
        setMode={setMode}
      />
    </div>
  )
}
