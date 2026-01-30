"use client"

import { useState, useEffect, useCallback } from "react"
import { MessageSquareDashed } from "lucide-react"
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

  // Load messages from localStorage on mount
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
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
      console.error("Failed to load from localStorage:", e)
    } finally {
      setIsLoaded(true)
    }
  }, [])

  // Persist messages to localStorage whenever they change
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(messages))
    } catch (e) {
      console.error("Failed to save messages to localStorage:", e)
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
        throw new Error("Upload failed")
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

      const summaryMessage: Message = {
        id: generateId(),
        role: "assistant",
        content: `**Data Summary:**\n${data.summary || "I have analyzed the schema. You can ask me to visualize distributions, detect outliers, or run statistical tests."}`,
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
    async (content: string) => {
      if (!content.trim() || isStreaming || !isFileUploaded) return

      setError(null)

      const userMessage: Message = {
        id: generateId(),
        role: "user",
        content: content.trim(),
        createdAt: new Date(),
      }

      setMessages((prev) => [...prev, userMessage])
      setIsStreaming(true)

      try {
        const response = await fetch(`${API_BASE_URL}/chat`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            message: content.trim(),
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

        setMessages((prev) => [...prev, ...newMessages])
      } catch (e) {
        console.error("Error sending message:", e)
        setError(e instanceof Error ? e.message : "An error occurred")
      } finally {
        setIsStreaming(false)
      }
    },
    [isStreaming, isFileUploaded],
  )

  const retry = useCallback(() => {
    if (messages.length === 0) return
    const lastUserMessage = [...messages].reverse().find((m) => m.role === "user")
    if (lastUserMessage) {
      const index = messages.findIndex((m) => m.id === lastUserMessage.id)
      setMessages(messages.slice(0, index))
      setError(null)
      setTimeout(() => sendMessage(lastUserMessage.content), 100)
    }
  }, [messages, sendMessage])

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
    localStorage.removeItem(STORAGE_KEY)
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

      <MessageList messages={messages} isStreaming={isStreaming} error={error} onRetry={retry} isLoaded={isLoaded} />

      <Composer
        onSend={sendMessage}
        onStop={stopStreaming}
        isStreaming={isStreaming}
        disabled={!!error}
        onUpload={handleUpload}
        isReady={isFileUploaded}
      />
    </div>
  )
}
