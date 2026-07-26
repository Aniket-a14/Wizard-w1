"use client"

import {
  AlertTriangle,
  BarChart3,
  Database,
  PanelRightOpen,
  Plus,
  Sparkles,
  WifiOff,
} from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { ArtifactsPanel, type ArtifactTab } from "@/components/chat/artifacts-panel"
import { Composer } from "@/components/chat/composer"
import { Message } from "@/components/chat/message"
import { ModelPicker } from "@/components/chat/model-picker"
import { api, clearStoredSessionId } from "@/lib/api"
import type { Artifact, DatasetSummary, ServerConfig } from "@/lib/types"
import { useChatStream } from "@/lib/use-chat-stream"
import { cn } from "@/lib/utils"

const SUGGESTIONS = [
  "Summarise this dataset and flag data quality issues",
  "Show the distribution of each numeric column",
  "Which columns are most correlated with each other?",
  "Find outliers and explain what they represent",
]

export function ChatShell() {
  const [config, setConfig] = useState<ServerConfig | null>(null)
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [activeDataset, setActiveDataset] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [mode, setMode] = useState<"planning" | "fast">("planning")

  const [panelOpen, setPanelOpen] = useState(false)
  const [panelTab, setPanelTab] = useState<ArtifactTab>("chart")
  const [chartVersion, setChartVersion] = useState(0)
  const [chartImage, setChartImage] = useState<string | null>(null)

  const scrollRef = useRef<HTMLDivElement>(null)
  const pinnedToBottom = useRef(true)

  const onArtifact = useCallback((artifact: Artifact) => {
    if (artifact.kind === "plot_html") {
      setChartImage(null)
      setChartVersion((value) => value + 1)
      setPanelTab("chart")
      setPanelOpen(true)
    } else if (artifact.kind === "plot_png" && artifact.data) {
      setChartImage(`data:image/png;base64,${artifact.data}`)
      setChartVersion((value) => value + 1)
      setPanelTab("chart")
      setPanelOpen(true)
    }
  }, [])

  const { messages, connection, isRunning, sendMessage, respondToApproval, cancel, clear } =
    useChatStream({ onArtifact })

  const refreshSession = useCallback(async () => {
    try {
      const session = await api.session()
      setDatasets(session.datasets)
      setActiveDataset(session.active_dataset)
    } catch {
      setDatasets([])
      setActiveDataset(null)
    }
  }, [])

  useEffect(() => {
    void api.config().then(setConfig).catch(() => setConfig(null))
    void refreshSession()
  }, [refreshSession])

  // Follow the stream, but stop fighting the user if they scroll up to read.
  useEffect(() => {
    const node = scrollRef.current
    if (node && pinnedToBottom.current) {
      node.scrollTop = node.scrollHeight
    }
  }, [messages])

  const handleScroll = useCallback(() => {
    const node = scrollRef.current
    if (!node) return
    pinnedToBottom.current = node.scrollHeight - node.scrollTop - node.clientHeight < 120
  }, [])

  const handleUpload = useCallback(
    async (file: File) => {
      setUploading(true)
      setUploadError(null)
      try {
        await api.upload(file)
        await refreshSession()
        setPanelTab("data")
        setPanelOpen(true)
      } catch (exception) {
        setUploadError(exception instanceof Error ? exception.message : "Upload failed.")
      } finally {
        setUploading(false)
      }
    },
    [refreshSession],
  )

  const handleActivateDataset = useCallback(
    async (name: string) => {
      await api.activateDataset(name)
      await refreshSession()
    },
    [refreshSession],
  )

  const handleNewChat = useCallback(async () => {
    clear()
    setChartVersion(0)
    setChartImage(null)
    setPanelOpen(false)
    try {
      await api.deleteSession()
    } catch {
      // The session may already be gone; a fresh id is minted on the next call.
    }
    clearStoredSessionId()
    await refreshSession()
  }, [clear, refreshSession])

  const hasData = Boolean(activeDataset)
  const activeSummary = useMemo(
    () => datasets.find((dataset) => dataset.name === activeDataset) ?? null,
    [datasets, activeDataset],
  )

  return (
    <div className="flex h-screen w-full flex-col bg-background text-foreground">
      <header className="flex h-13 shrink-0 items-center justify-between border-b border-border px-3">
        <div className="flex min-w-0 items-center gap-2">
          <button
            type="button"
            onClick={() => void handleNewChat()}
            className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <Plus className="h-3.5 w-3.5" />
            New chat
          </button>

          {activeSummary && (
            <button
              type="button"
              onClick={() => {
                setPanelTab("data")
                setPanelOpen(true)
              }}
              className="flex min-w-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <Database className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
              <span className="max-w-[220px] truncate">{activeSummary.name}</span>
              <span className="shrink-0 text-muted-foreground/60">
                {activeSummary.rows.toLocaleString()}×{activeSummary.column_count}
              </span>
            </button>
          )}
        </div>

        <div className="flex items-center gap-1">
          {connection !== "open" && (
            <span
              className="flex items-center gap-1 rounded-lg bg-amber-500/10 px-2 py-1 text-[11px] font-medium text-amber-600 dark:text-amber-400"
              role="status"
            >
              <WifiOff className="h-3 w-3" />
              {connection === "connecting" ? "Connecting…" : "Reconnecting…"}
            </span>
          )}

          {config && !config.sandbox_available && (
            <span
              className="flex items-center gap-1 rounded-lg bg-amber-500/10 px-2 py-1 text-[11px] font-medium text-amber-600 dark:text-amber-400"
              title="Docker is unreachable, so code runs in a restricted local interpreter."
            >
              <AlertTriangle className="h-3 w-3" />
              No sandbox
            </span>
          )}

          <ModelPicker />

          <button
            type="button"
            onClick={() => setPanelOpen((value) => !value)}
            aria-label="Toggle workspace"
            className={cn(
              "flex h-8 w-8 items-center justify-center rounded-lg transition-colors",
              panelOpen ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted",
            )}
          >
            <PanelRightOpen className="h-4 w-4" />
          </button>
        </div>
      </header>

      <div className={cn("flex min-h-0 flex-1 flex-col transition-[margin] duration-300", panelOpen && "lg:mr-[560px]")}>
        <div ref={scrollRef} onScroll={handleScroll} className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-3xl pb-6 pt-4">
            {messages.length === 0 ? (
              <EmptyState
                hasData={hasData}
                onPick={(prompt) => sendMessage(prompt, mode)}
                formats={config?.supported_formats ?? ["csv"]}
              />
            ) : (
              messages.map((message) => (
                <Message
                  key={message.id}
                  message={message}
                  onApprove={respondToApproval}
                  onOpenArtifact={onArtifact}
                />
              ))
            )}

            {uploadError && (
              <div className="mx-4 mt-3 flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-700 dark:text-rose-300">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{uploadError}</span>
              </div>
            )}
          </div>
        </div>

        <Composer
          onSend={sendMessage}
          onStop={cancel}
          onUpload={(file) => void handleUpload(file)}
          isRunning={isRunning}
          isUploading={uploading}
          hasData={hasData}
          acceptedFormats={config?.supported_formats ?? ["csv"]}
          mode={mode}
          onModeChange={setMode}
        />
      </div>

      <ArtifactsPanel
        open={panelOpen}
        onClose={() => setPanelOpen(false)}
        tab={panelTab}
        onTabChange={setPanelTab}
        chartVersion={chartVersion}
        chartImage={chartImage}
        datasets={datasets}
        activeDataset={activeDataset}
        onActivateDataset={(name) => void handleActivateDataset(name)}
      />
    </div>
  )
}

function EmptyState({
  hasData,
  onPick,
  formats,
}: {
  hasData: boolean
  onPick: (prompt: string) => void
  formats: string[]
}) {
  return (
    <div className="flex flex-col items-center px-6 py-16 text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-lg">
        <Sparkles className="h-6 w-6" />
      </div>
      <h1 className="text-2xl font-semibold tracking-tight">What should we analyse?</h1>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">
        {hasData
          ? "Your data is loaded. Ask a question and I will plan the analysis, write the Python, run it in a sandbox and explain the result."
          : `Attach a dataset to begin — ${formats.slice(0, 6).join(", ")} are supported.`}
      </p>

      {hasData && (
        <div className="mt-7 grid w-full max-w-xl gap-2 sm:grid-cols-2">
          {SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => onPick(suggestion)}
              className="rounded-xl border border-border bg-card px-3.5 py-3 text-left text-[13px] leading-snug transition-colors hover:border-primary/40 hover:bg-muted"
            >
              <BarChart3 className="mb-1.5 h-3.5 w-3.5 text-emerald-600" />
              {suggestion}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
