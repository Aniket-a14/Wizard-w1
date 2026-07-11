"use client"

import { useState, useEffect, useCallback } from "react"
import { cn } from "@/lib/utils"
import { MessageSquareDashed, BookOpenText, FileImage, Folder, Table2, BarChart3 } from "lucide-react"
import { MessageList } from "./message-list"
import { Composer } from "./composer"
import { Button } from "@/components/ui/button"
import { WorkspaceExplorer } from "./workspace-explorer"
import { DataGrid } from "./data-grid"

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
  downloads?: string[]
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

  // Workspace Split State
  const [activeTab, setActiveTab] = useState<"files" | "table" | "plots">("files")
  const [selectedCsv, setSelectedCsv] = useState<string | null>(null)
  const [selectedImage, setSelectedImage] = useState<string | null>(null)

  // Load messages from sessionStorage on mount
  useEffect(() => {
    try {
      const stored = sessionStorage.getItem(STORAGE_KEY)
      if (stored) {
        const parsed = JSON.parse(stored) as Message[]
        const formatted = parsed.map(m => ({
          ...m,
          createdAt: new Date(m.createdAt)
        }))
        setMessages(formatted)
        
        // Check if a dataset was previously loaded successfully
        const hasSuccessMsg = formatted.some(m => m.content.includes("loaded successfully!"))
        if (hasSuccessMsg) {
          setIsFileUploaded(true)
        }
      }
    } catch (e) {
      console.error("Failed to load messages from sessionStorage:", e)
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

      // Consolidate into a single clean upload-info message
      // Show only the first 10 column names to avoid clutter
      const maxCols = 10
      const shownCols = data.columns.slice(0, maxCols)
      const columnList = shownCols.map((c: string) => `\`${c}\``).join(", ")
      const moreColumns = data.columns.length > maxCols
        ? ` and **${data.columns.length - maxCols}** more`
        : ""

      // Handle cleaning status — suppress raw errors, show clean status
      let cleaningStatus = ""
      if (data.cleaning_result) {
        const isError = data.cleaning_result.toLowerCase().includes("error") ||
                        data.cleaning_result.toLowerCase().includes("refused")
        if (isError) {
          cleaningStatus = "\n\n⚠️ *Auto-cleaning skipped — you can clean data manually via chat.*"
        } else {
          cleaningStatus = `\n\n🧹 ${data.cleaning_result}`
        }
      }

      // NOTE: data.summary contains the verbose raw schema dump — we intentionally
      // exclude it from the chat message. Users can view the actual data in the Data tab.
      const uploadMessage: Message = {
        id: generateId(),
        role: "assistant",
        content: `✅ **${data.filename}** loaded successfully!\n\n📊 **${data.shape[0].toLocaleString()}** rows × **${data.shape[1]}** columns\n\n**Columns:** ${columnList}${moreColumns}${cleaningStatus}\n\nYour data is ready — switch to the **Data** tab to browse, or ask me anything!`,
        createdAt: new Date(),
      }

      setMessages((prev) => [...prev, uploadMessage])
      setIsFileUploaded(true)
      
      // Automatically show dataset in grid preview
      setSelectedCsv("dataset.csv")
      setActiveTab("table")
    } catch (e) {
      console.error("Error uploading file:", e)
      setError(e instanceof Error ? e.message : "An error occurred during upload")
      setIsFileUploaded(false)
    } finally {
      setIsStreaming(false)
    }
  }, [])

  // Send a message to the AI via WebSockets
  const sendMessage = useCallback(
    async (
      content: string,
      currentMode: "planning" | "fast" = "planning",
      isConfirmedPlan: boolean = false,
      extraPayload: { approved?: boolean; tool?: string; query?: string } = {}
    ) => {
      if (!content.trim() || isStreaming) return

      setError(null)

      const userMessage: Message = {
        id: generateId(),
        role: "user",
        content: content.trim(),
        createdAt: new Date(),
      }

      if (!isConfirmedPlan && !extraPayload.approved) {
        setMessages((prev) => [...prev, userMessage])
      }

      if (!isFileUploaded) {
        setIsStreaming(true)
        setTimeout(() => {
          const helperMsg: Message = {
            id: generateId(),
            role: "assistant",
            content: "👋 **Welcome to Wizard w1!** I am your autonomous Data Science assistant.\n\nTo begin analyzing, cleaning, or plotting data, **please upload a CSV dataset** by clicking the paperclip icon 📎 below.\n\nOnce loaded, I can help you with operations like:\n- Visualizing correlation matrices\n- Outlier detection and handling\n- Performing hypothesis tests and regression models\n- Semantic cleaning of messy inputs",
            createdAt: new Date(),
          }
          setMessages((prev) => [...prev, helperMsg])
          setIsStreaming(false)
        }, 600)
        return
      }

      setIsStreaming(true)

      const wsUrl = API_BASE_URL.replace(/^http/, "ws") + "/ws/chat"
      const ws = new WebSocket(wsUrl)

      // Spawn a temporary status block
      const assistantMessageId = generateId()
      const assistantMsg: Message = {
        id: assistantMessageId,
        role: "assistant",
        content: "Thinking...",
        createdAt: new Date(),
      }
      setMessages((prev) => [...prev, assistantMsg])

      ws.onopen = () => {
        const payload = {
          message: content.trim(),
          mode: currentMode,
          is_confirmed_plan: isConfirmedPlan,
          ...extraPayload
        }
        ws.send(JSON.stringify(payload))
      }

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)

        if (data.type === "status") {
          // Show live step progression — update the status line
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessageId
                ? { ...m, content: `${data.content}` }
                : m
            )
          )
        } else if (data.type === "thought") {
          // Stream thought content — will be shown live during streaming
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessageId
                ? { ...m, thought: data.content }
                : m
            )
          )
        } else if (data.type === "code") {
          // Update status to show code is executing
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessageId
                ? { ...m, content: `Executing code...` }
                : m
            )
          )
        } else if (data.type === "approval_required") {
          // Update the existing message in-place — preserve thought context and display plan
          const combinedContent = `${data.plan || ""}\n\n${data.prompt || ""}`.trim()
          setMessages((prev) =>
            prev.map((m) => {
              if (m.id !== assistantMessageId) return m
              return {
                ...m,
                content: combinedContent,
                // Keep the thought block from the thinking phase
                thought: m.thought,
                actions: [
                  {
                    label: "Allow",
                    variant: "primary" as const,
                    onClick: () => {
                      sendMessage(content, currentMode, isConfirmedPlan, {
                        approved: true,
                        tool: data.tool,
                        query: data.query
                      })
                      // Replace the approval message with a confirmation
                      setMessages((curr) =>
                        curr.map((msg) =>
                          msg.id === assistantMessageId
                            ? { ...msg, content: "✅ Plan approved — executing...", actions: undefined }
                            : msg
                        )
                      )
                    }
                  },
                  {
                    label: "Reject",
                    variant: "secondary" as const,
                    onClick: () => {
                      sendMessage(content, currentMode, isConfirmedPlan, {
                        approved: false,
                        tool: data.tool,
                        query: data.query
                      })
                      setMessages((curr) =>
                        curr.map((msg) =>
                          msg.id === assistantMessageId
                            ? { ...msg, content: "❌ Plan rejected.", actions: undefined }
                            : msg
                        )
                      )
                    }
                  }
                ]
              }
            })
          )
          ws.close()
          setIsStreaming(false)
        } else if (data.type === "final") {
          ws.close()

          // Clean the response: strip raw data dumps, errors, and internal agent blocks
          let cleanResponse = data.response || ""
          // Remove raw code blocks
          cleanResponse = cleanResponse.replace(/```[\s\S]*?```/g, "").trim()
          // Remove sandbox/connection error messages
          cleanResponse = cleanResponse.replace(/Sandbox\s+(communication\s+)?error[^\n]*/gi, "").trim()
          cleanResponse = cleanResponse.replace(/\[Errno\s+\d+\][^\n]*/g, "").trim()
          cleanResponse = cleanResponse.replace(/Connection refused[^\n]*/gi, "").trim()
          cleanResponse = cleanResponse.replace(/Error:?\s*(Sandbox|Container|Socket)[^\n]*/gi, "").trim()
          // Remove internal "Council's Review" / reviewer blocks
          cleanResponse = cleanResponse.replace(/###?\s*🛡️?\s*The Council'?s Review[\s\S]*?(?=\n##|\n\n[^-]|$)/gi, "").trim()
          cleanResponse = cleanResponse.replace(/- (Visualizer|Statistician|Architect|Reviewer)\s*:\s*✅[^\n]*/gi, "").trim()
          // Remove raw tabular output lines
          cleanResponse = cleanResponse
            .split("\n")
            .filter((line: string) => {
              const trimmed = line.trim()
              if (/^\d+\s{2,}/.test(trimmed)) return false
              if (/^(count|mean|std|min|max|25%|50%|75%)\s{2,}/.test(trimmed)) return false
              if (/^[-=|:+]+$/.test(trimmed)) return false
              // Skip raw traceback lines
              if (/^(Traceback|File "|  File |    |TypeError|ValueError|KeyError|AttributeError|ImportError)/.test(trimmed)) return false
              return true
            })
            .join("\n")
            .replace(/\n{3,}/g, "\n\n")
            .trim()

          if (!cleanResponse) {
            cleanResponse = "✅ Analysis complete! Check the **Plots** tab for visualizations or the **Data** tab for results."
          }

          // Images go to Plots tab only
          if (data.image) {
            setSelectedImage(`data:image/png;base64,${data.image}`)
            setActiveTab("plots")
          }

          // Remove the status placeholder and insert an empty final message
          setMessages((prev) => {
            const cleaned = prev.filter((m) => m.id !== assistantMessageId)
            const finalMsg: Message = {
              id: assistantMessageId,
              role: "assistant",
              content: "",
              thought: prev.find((m) => m.id === assistantMessageId)?.thought,
              createdAt: new Date(),
              downloads: data.downloads
            }
            return [...cleaned, finalMsg]
          })

          // Progressive word-by-word reveal — like ChatGPT/Claude streaming
          const words = cleanResponse.split(/(\s+)/)
          let wordIndex = 0
          const wordsPerTick = 4 // reveal ~4 words per tick
          const revealInterval = setInterval(() => {
            wordIndex += wordsPerTick
            const revealed = words.slice(0, wordIndex).join("")

            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMessageId
                  ? { ...m, content: revealed }
                  : m
              )
            )

            if (wordIndex >= words.length) {
              clearInterval(revealInterval)
              // Ensure final content is complete
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMessageId
                    ? { ...m, content: cleanResponse }
                    : m
                )
              )
              setIsStreaming(false)
            }
          }, 30) // 30ms per tick = smooth stream
        } else if (data.type === "error") {
          setError(data.content)
          setMessages((prev) => prev.filter((m) => m.id !== assistantMessageId))
          ws.close()
          setIsStreaming(false)
        }
      }

      ws.onerror = (err) => {
        console.error("WebSocket error:", err)
        setError("Could not connect to WebSocket chat server.")
        setMessages((prev) => prev.filter((m) => m.id !== assistantMessageId))
        setIsStreaming(false)
      }

      ws.onclose = () => {
        setIsStreaming(false)
      }
    },
    [isStreaming, isFileUploaded, setMessages, setError, setIsStreaming, API_BASE_URL]
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
    // Abort handler
  }, [])

  const clearChat = useCallback(() => {
    playClick()
    setMessages([])
    setError(null)
    setIsFileUploaded(false)
    setSelectedCsv(null)
    setSelectedImage(null)
    setActiveTab("files")
    sessionStorage.removeItem(STORAGE_KEY)
  }, [playClick])

  const tabs = [
    { key: "files" as const, label: "Files", icon: Folder },
    { key: "table" as const, label: "Data", icon: Table2 },
    { key: "plots" as const, label: "Plots", icon: BarChart3 },
  ]

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-stone-100 font-sans antialiased">
      
      {/* LEFT PANEL: Chat Shell (Width: 42%) */}
      <div className="flex flex-col w-[42%] h-full relative bg-stone-50 overflow-hidden">
        {/* Top bar with actions */}
        <div className="flex items-center justify-between px-4 h-13 shrink-0 border-b border-stone-200/60 bg-white/60 backdrop-blur-md z-20">
          <Button
            onClick={clearChat}
            variant="ghost"
            size="icon"
            className="h-8 w-8 rounded-lg hover:bg-stone-100 text-stone-500 hover:text-stone-700"
            aria-label="Reset chat"
          >
            <MessageSquareDashed className="w-4 h-4" />
          </Button>

          <Button
            onClick={generateReport}
            disabled={!isFileUploaded || isStreaming}
            variant="ghost"
            className="rounded-lg text-stone-500 hover:text-stone-700 hover:bg-stone-100 flex items-center gap-1.5 px-3 h-8 text-xs font-medium"
          >
            <BookOpenText className="w-3.5 h-3.5 text-emerald-600" />
            Report
          </Button>
        </div>

        {/* Messages area — flex-1 so it fills available space */}
        <div className="flex-1 overflow-hidden relative">
          <MessageList messages={messages} isStreaming={isStreaming} error={error} onRetry={retry} isLoaded={isLoaded} />
        </div>

        {/* Composer sits at bottom naturally */}
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

      {/* RIGHT PANEL: Workspace View (Width: 58%) */}
      <div className="flex-1 flex flex-col h-full workspace-gradient panel-divider overflow-hidden">
        
        {/* Workspace Tab Bar */}
        <div className="flex items-center justify-between border-b border-stone-200/50 px-4 h-13 select-none shrink-0 bg-white/40 backdrop-blur-md">
          <div className="flex items-center gap-1 bg-stone-100/80 rounded-lg p-0.5">
            {tabs.map((tab) => {
              const Icon = tab.icon
              const isActive = activeTab === tab.key
              return (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={cn(
                    "px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200 flex items-center gap-1.5",
                    isActive
                      ? "tab-active text-white"
                      : "text-stone-500 hover:text-stone-700 hover:bg-stone-200/60"
                  )}
                >
                  <Icon className={cn("w-3.5 h-3.5", isActive ? "text-stone-300" : "")} />
                  {tab.label}
                </button>
              )
            })}
          </div>
        </div>

        {/* Workspace Tab Contents */}
        <div className="flex-1 overflow-hidden">
          {activeTab === "files" && (
            <WorkspaceExplorer
              apiBaseUrl={API_BASE_URL}
              onSelectCsv={(path) => {
                setSelectedCsv(path)
                setActiveTab("table")
              }}
              onSelectImage={(url) => {
                setSelectedImage(url)
                setActiveTab("plots")
              }}
            />
          )}

          {activeTab === "table" && (
            <DataGrid apiBaseUrl={API_BASE_URL} csvPath={selectedCsv} />
          )}

          {activeTab === "plots" && (
            <div className="flex flex-col items-center justify-center h-full p-6 bg-stone-950">
              {selectedImage ? (
                <div className="relative max-w-full max-h-full flex items-center justify-center p-3 rounded-xl bg-stone-900 overflow-auto">
                  <img
                    src={selectedImage}
                    alt="Plot Preview"
                    className="max-h-[calc(100vh-120px)] object-contain rounded-lg shadow-lg border border-stone-800"
                  />
                </div>
              ) : (
                <div className="text-center text-stone-500">
                  <FileImage className="w-12 h-12 mx-auto mb-3 opacity-15" />
                  <p className="text-sm font-medium text-stone-400">No plots yet</p>
                  <p className="text-xs text-stone-600 mt-1.5 max-w-[240px]">Run analysis or select a plot from workspace files to preview here.</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      
    </div>
  )
}
