"use client"

import {
  BarChart3,
  Download,
  FileText,
  Folder,
  Loader2,
  RefreshCw,
  Table2,
  X,
} from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { DataGrid } from "@/components/data-grid"
import { api, workspaceFileUrl } from "@/lib/api"
import type { DatasetSummary, WorkspaceFileEntry } from "@/lib/types"
import { cn } from "@/lib/utils"

export type ArtifactTab = "chart" | "data" | "files"

interface ArtifactsPanelProps {
  open: boolean
  onClose: () => void
  tab: ArtifactTab
  onTabChange: (tab: ArtifactTab) => void
  /** Bumped whenever a run produces a new chart, to bust the iframe cache. */
  chartVersion: number
  chartImage: string | null
  datasets: DatasetSummary[]
  activeDataset: string | null
  onActivateDataset: (name: string) => void
}

const TABS: { key: ArtifactTab; label: string; icon: typeof BarChart3 }[] = [
  { key: "chart", label: "Chart", icon: BarChart3 },
  { key: "data", label: "Data", icon: Table2 },
  { key: "files", label: "Files", icon: Folder },
]

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

/**
 * Slide-over workspace.
 *
 * Kept out of the conversation flow so the chat owns the viewport, matching the
 * ChatGPT canvas / Gemini panel pattern. Opens automatically when a run emits a
 * chart.
 */
export function ArtifactsPanel({
  open,
  onClose,
  tab,
  onTabChange,
  chartVersion,
  chartImage,
  datasets,
  activeDataset,
  onActivateDataset,
}: ArtifactsPanelProps) {
  const [files, setFiles] = useState<WorkspaceFileEntry[]>([])
  const [loadingFiles, setLoadingFiles] = useState(false)

  const loadFiles = useCallback(async () => {
    setLoadingFiles(true)
    try {
      const response = await api.workspaceFiles()
      setFiles(response.files)
    } catch {
      setFiles([])
    } finally {
      setLoadingFiles(false)
    }
  }, [])

  useEffect(() => {
    if (open && tab === "files") void loadFiles()
  }, [open, tab, loadFiles, chartVersion])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [open, onClose])

  return (
    <>
      {open && (
        <button
          type="button"
          aria-label="Close workspace"
          onClick={onClose}
          className="fixed inset-0 z-30 bg-foreground/15 backdrop-blur-[3px] lg:hidden"
        />
      )}

      <aside
        className={cn(
          "fixed right-0 top-0 z-40 flex h-full w-full max-w-[560px] flex-col border-l border-border bg-background shadow-lg",
          "transition-transform duration-[var(--duration-slow)] ease-[var(--ease-out-expo)]",
          open ? "translate-x-0" : "translate-x-full",
        )}
        aria-hidden={!open}
      >
        <div className="flex h-14 shrink-0 items-center justify-between border-b border-border px-3">
          <div className="flex items-center gap-0.5 rounded-lg bg-muted p-0.5" role="tablist">
            {TABS.map((entry) => {
              const Icon = entry.icon
              return (
                <button
                  key={entry.key}
                  type="button"
                  role="tab"
                  aria-selected={tab === entry.key}
                  onClick={() => onTabChange(entry.key)}
                  className={cn(
                    "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12px] font-medium",
                    "transition-[background-color,color,box-shadow] duration-[var(--duration-fast)]",
                    tab === entry.key
                      ? "bg-card text-foreground shadow-xs"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {entry.label}
                </button>
              )
            })}
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close workspace"
            className="flex h-7 w-7 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-hidden">
          {tab === "chart" && (
            <div className="h-full p-3">
              {chartImage ? (
                // A base64 data URI produced at runtime cannot be optimised by
                // next/image, so a plain <img> is the correct element here.
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={chartImage}
                  alt="Generated chart"
                  className="mx-auto max-h-full rounded-lg border border-border object-contain"
                />
              ) : chartVersion > 0 ? (
                <iframe
                  key={chartVersion}
                  src={workspaceFileUrl("plot.html", true)}
                  title="Generated chart"
                  className="h-full w-full rounded-lg border border-border bg-white"
                  sandbox="allow-scripts"
                />
              ) : (
                <EmptyPanel
                  icon={BarChart3}
                  title="No chart yet"
                  hint="Ask for a plot and it will appear here."
                />
              )}
            </div>
          )}

          {tab === "data" && (
            <div className="flex h-full flex-col">
              {datasets.length > 1 && (
                <div className="flex shrink-0 flex-wrap gap-1.5 border-b border-border p-2">
                  {datasets.map((dataset) => (
                    <button
                      key={dataset.name}
                      type="button"
                      onClick={() => onActivateDataset(dataset.name)}
                      className={cn(
                        "rounded-md px-2.5 py-1 text-[11.5px] font-medium transition-colors duration-[var(--duration-fast)]",
                        dataset.name === activeDataset
                          ? "bg-primary text-primary-foreground shadow-xs"
                          : "bg-muted text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {dataset.name}
                    </button>
                  ))}
                </div>
              )}
              <div className="min-h-0 flex-1">
                {activeDataset ? (
                  <DataGrid dataset={activeDataset} />
                ) : (
                  <EmptyPanel icon={Table2} title="No data loaded" hint="Upload a file to browse it here." />
                )}
              </div>
            </div>
          )}

          {tab === "files" && (
            <div className="h-full overflow-y-auto p-3">
              <div className="mb-2 flex items-center justify-between">
                <p className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-muted-foreground">
                  {files.length} file{files.length === 1 ? "" : "s"}
                </p>
                <button
                  type="button"
                  onClick={() => void loadFiles()}
                  aria-label="Refresh file list"
                  className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground hover:bg-muted"
                >
                  <RefreshCw className={cn("h-3 w-3", loadingFiles && "animate-spin")} />
                </button>
              </div>

              {loadingFiles && files.length === 0 && (
                <div className="flex justify-center py-8">
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                </div>
              )}

              {!loadingFiles && files.length === 0 && (
                <EmptyPanel icon={Folder} title="Workspace is empty" hint="Generated files land here." />
              )}

              <ul className="space-y-1">
                {files.map((file) => (
                  <li key={file.path}>
                    <a
                      href={workspaceFileUrl(file.path)}
                      download={file.name}
                      className="flex items-center gap-2.5 rounded-lg border border-transparent px-2.5 py-2 transition-colors duration-[var(--duration-fast)] hover:border-border hover:bg-accent/50"
                    >
                      <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1 truncate text-[12.5px]">{file.name}</span>
                      <span className="tabular shrink-0 text-[10.5px] text-muted-foreground">
                        {formatBytes(file.size)}
                      </span>
                      <Download className="h-3 w-3 shrink-0 text-muted-foreground" />
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </aside>
    </>
  )
}

function EmptyPanel({
  icon: Icon,
  title,
  hint,
}: {
  icon: typeof BarChart3
  title: string
  hint: string
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
      <span className="mb-2 flex h-12 w-12 items-center justify-center rounded-2xl border border-border bg-card shadow-xs">
        <Icon className="h-5 w-5 text-muted-foreground/50" />
      </span>
      <p className="text-[14px] font-medium">{title}</p>
      <p className="max-w-[240px] text-[12.5px] leading-relaxed text-muted-foreground">{hint}</p>
    </div>
  )
}
