"use client"

import { Check, Database, Loader2, Trash2, UploadCloud } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { DataGrid } from "@/components/data-grid"
import { PageHeader } from "@/components/page-header"
import { api } from "@/lib/api"
import type { DatasetSummary, ServerConfig } from "@/lib/types"
import { useSound } from "@/lib/use-sound"
import { cn } from "@/lib/utils"

function formatCount(value: number): string {
  return value.toLocaleString()
}

/**
 * Everything about the loaded data, on one page.
 *
 * The chat's slide-over shows a preview grid, but only for the active dataset
 * and only while a conversation is open. This is the surface for the questions
 * that come *before* asking anything: what is loaded, what is in it, what is
 * missing, and which one is active.
 */
export function DataWorkbench() {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [activeDataset, setActiveDataset] = useState<string | null>(null)
  const [config, setConfig] = useState<ServerConfig | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { playSound } = useSound()

  const refresh = useCallback(async () => {
    try {
      const session = await api.session()
      setDatasets(session.datasets)
      setActiveDataset(session.active_dataset)
      // Keep the viewer on whatever the user was looking at; fall back to active.
      setSelected((current) =>
        current && session.datasets.some((entry) => entry.name === current)
          ? current
          : session.active_dataset,
      )
    } catch {
      setDatasets([])
      setActiveDataset(null)
    }
  }, [])

  useEffect(() => {
    void api.config().then(setConfig).catch(() => setConfig(null))
    void refresh()
  }, [refresh])

  const upload = useCallback(
    async (file: File | undefined) => {
      if (!file) return
      setUploading(true)
      setError(null)
      try {
        await api.upload(file)
        await refresh()
        playSound("click")
      } catch (exception) {
        setError(exception instanceof Error ? exception.message : "Upload failed.")
      } finally {
        setUploading(false)
      }
    },
    [playSound, refresh],
  )

  const activate = useCallback(
    async (name: string) => {
      setBusy(name)
      try {
        await api.activateDataset(name)
        await refresh()
        playSound("click")
      } catch (exception) {
        setError(exception instanceof Error ? exception.message : "Could not switch dataset.")
      } finally {
        setBusy(null)
      }
    },
    [playSound, refresh],
  )

  const remove = useCallback(
    async (name: string) => {
      setBusy(name)
      try {
        await api.deleteDataset(name)
        await refresh()
      } catch (exception) {
        setError(exception instanceof Error ? exception.message : "Could not remove dataset.")
      } finally {
        setBusy(null)
      }
    },
    [refresh],
  )

  const viewing = useMemo(
    () => datasets.find((entry) => entry.name === selected) ?? null,
    [datasets, selected],
  )

  const accept = (config?.supported_formats ?? ["csv"])
    .map((extension) => `.${extension.replace(/^\./, "")}`)
    .join(",")

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <PageHeader
        eyebrow="Workspace"
        title="Data"
        description="Everything loaded into this session. Files are read where they sit — nothing is uploaded off this machine."
        actions={
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept={accept}
              onChange={(event) => {
                void upload(event.target.files?.[0])
                event.target.value = ""
              }}
              className="hidden"
              aria-label="Load a dataset"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="flex h-9 items-center gap-2 rounded-lg bg-[linear-gradient(120deg,var(--brand),var(--brand-2))] px-4 text-[13px] font-medium text-brand-foreground shadow-brand transition-all duration-[var(--duration-fast)] hover:brightness-105 active:scale-[0.985] disabled:opacity-50"
            >
              {uploading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <UploadCloud className="h-3.5 w-3.5" />
              )}
              {uploading ? "Reading…" : "Load a file"}
            </button>
          </>
        }
      />

      {error && (
        <div className="mx-6 mt-5 flex items-start gap-2.5 rounded-xl border border-destructive/25 bg-destructive/8 p-3.5 text-[13.5px] text-destructive md:mx-9">
          {error}
        </div>
      )}

      {datasets.length === 0 ? (
        <div
          onDragOver={(event) => {
            event.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault()
            setDragging(false)
            void upload(event.dataTransfer.files?.[0])
          }}
          className="m-6 flex flex-1 flex-col items-center justify-center rounded-2xl border-2 border-dashed p-12 text-center transition-colors duration-[var(--duration-base)] md:m-9"
          style={{ borderColor: dragging ? "var(--brand)" : "var(--border)" }}
        >
          <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-border bg-card shadow-xs">
            <Database className="h-6 w-6 text-muted-foreground/60" />
          </span>
          <p className="text-[17px] font-medium tracking-[-0.02em]">Nothing loaded yet</p>
          <p className="mt-2 max-w-sm text-[13.5px] leading-relaxed text-muted-foreground">
            Drop a file here, or use the button above.{" "}
            {(config?.supported_formats ?? ["csv"]).slice(0, 6).join(", ")} are read natively — up to{" "}
            {config?.max_upload_mb ?? 512} MB.
          </p>
        </div>
      ) : (
        <>
          <div className="grid gap-3 px-6 py-6 md:grid-cols-2 md:px-9 lg:grid-cols-3">
            {datasets.map((dataset) => {
              const isActive = dataset.name === activeDataset
              const isViewing = dataset.name === selected
              return (
                <article
                  key={dataset.name}
                  className={cn(
                    "lift group relative rounded-xl border bg-card p-4 shadow-xs",
                    isViewing ? "border-brand/50 shadow-md" : "border-border",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => setSelected(dataset.name)}
                    className="block w-full text-left"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="min-w-0 truncate text-[14px] font-medium tracking-[-0.01em]">
                        {dataset.name}
                      </h3>
                      {isActive && (
                        <span className="flex shrink-0 items-center gap-1 rounded-md bg-success/12 px-1.5 py-0.5 text-[10px] font-medium text-success">
                          <Check className="h-2.5 w-2.5" />
                          Active
                        </span>
                      )}
                    </div>

                    <dl className="mt-3 grid grid-cols-3 gap-2">
                      <Stat label="Rows" value={formatCount(dataset.rows)} />
                      <Stat label="Columns" value={formatCount(dataset.column_count)} />
                      <Stat label="Format" value={dataset.source_format || "—"} />
                    </dl>
                  </button>

                  <div className="mt-3.5 flex items-center gap-1.5 border-t border-border pt-3">
                    {!isActive && (
                      <button
                        type="button"
                        onClick={() => void activate(dataset.name)}
                        disabled={busy === dataset.name}
                        className="rounded-md px-2 py-1 text-[11.5px] font-medium text-muted-foreground transition-colors duration-[var(--duration-fast)] hover:bg-muted hover:text-foreground disabled:opacity-50"
                      >
                        Make active
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => void remove(dataset.name)}
                      disabled={busy === dataset.name}
                      aria-label={`Remove ${dataset.name}`}
                      className="ml-auto flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors duration-[var(--duration-fast)] hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
                    >
                      {busy === dataset.name ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Trash2 className="h-3.5 w-3.5" />
                      )}
                    </button>
                  </div>
                </article>
              )
            })}
          </div>

          {viewing && (
            <section className="flex min-h-[26rem] flex-1 flex-col border-t border-border">
              <div className="flex shrink-0 items-center justify-between gap-3 px-6 py-3.5 md:px-9">
                <div className="min-w-0">
                  <h2 className="truncate text-[14px] font-semibold tracking-[-0.015em]">
                    {viewing.name}
                  </h2>
                  <p className="tabular mt-0.5 text-[12px] text-muted-foreground">
                    {formatCount(viewing.rows)} rows · {formatCount(viewing.column_count)} columns
                  </p>
                </div>
              </div>
              <div className="min-h-0 flex-1 border-t border-border">
                <DataGrid dataset={viewing.name} />
              </div>
            </section>
          )}
        </>
      )}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="font-mono text-[9.5px] uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </dt>
      <dd className="tabular mt-0.5 truncate text-[13px] font-medium">{value}</dd>
    </div>
  )
}
