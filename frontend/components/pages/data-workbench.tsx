"use client"

import { Check, Database, FileText, Loader2, Paperclip, Trash2, UploadCloud } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { DataGrid } from "@/components/data-grid"
import { PageHeader } from "@/components/page-header"
import { api } from "@/lib/api"
import type { DatasetSummary, DocumentSummary, ServerConfig } from "@/lib/types"
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
  const [documents, setDocuments] = useState<DocumentSummary[]>([])
  const [activeDataset, setActiveDataset] = useState<string | null>(null)
  const [config, setConfig] = useState<ServerConfig | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [attachingDoc, setAttachingDoc] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const documentInputRef = useRef<HTMLInputElement>(null)
  const { playSound } = useSound()

  const refresh = useCallback(async () => {
    try {
      const session = await api.session()
      setDatasets(session.datasets)
      setDocuments(session.documents ?? [])
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

  const attachDocument = useCallback(
    async (file: File | undefined) => {
      if (!file) return
      setAttachingDoc(true)
      setError(null)
      try {
        await api.uploadDocument(file)
        await refresh()
        playSound("click")
      } catch (exception) {
        setError(exception instanceof Error ? exception.message : "Could not attach the document.")
      } finally {
        setAttachingDoc(false)
      }
    },
    [playSound, refresh],
  )

  const removeDocument = useCallback(
    async (name: string) => {
      setBusy(name)
      try {
        await api.deleteDocument(name)
        await refresh()
      } catch (exception) {
        setError(exception instanceof Error ? exception.message : "Could not remove the document.")
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

                    {/* Every loaded table is in the sandbox namespace at once,
                        not just the active one — so the name generated code
                        uses to reach this table is worth showing. */}
                    {dataset.table_key && (
                      <p className="mt-2.5 truncate font-mono text-[11px] text-muted-foreground">
                        tables[&apos;{dataset.table_key}&apos;]
                      </p>
                    )}
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

          <ReferenceDocuments
            documents={documents}
            busy={busy}
            attaching={attachingDoc}
            inputRef={documentInputRef}
            onAttach={attachDocument}
            onRemove={removeDocument}
          />

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

/**
 * Reference documents: the context that says what the data *means*.
 *
 * A data dictionary, a fee schedule, the page explaining that `status = 'C'`
 * means cancelled and not complete. Hard questions turn on these more often
 * than on anything discoverable from the tables, and the agent retrieves from
 * them mid-analysis rather than having them pasted into every prompt.
 */
function ReferenceDocuments({
  documents,
  busy,
  attaching,
  inputRef,
  onAttach,
  onRemove,
}: {
  documents: DocumentSummary[]
  busy: string | null
  attaching: boolean
  inputRef: React.RefObject<HTMLInputElement | null>
  onAttach: (file: File | undefined) => void
  onRemove: (name: string) => void
}) {
  return (
    <section className="border-t border-border px-6 py-6 md:px-9">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-[-0.015em]">
            <FileText className="h-3.5 w-3.5 text-brand" />
            Reference documents
          </h2>
          <p className="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-muted-foreground">
            Data dictionaries, metric definitions, business rules. Not data — context. The agent reads
            these when a question turns on what a column actually means.
          </p>
        </div>

        <input
          ref={inputRef}
          type="file"
          accept=".md,.markdown,.txt,.rst,.text,.pdf,.docx,.html,.htm"
          onChange={(event) => {
            onAttach(event.target.files?.[0])
            event.target.value = ""
          }}
          className="hidden"
          aria-label="Attach a reference document"
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={attaching}
          className="flex h-9 shrink-0 items-center gap-2 rounded-lg border border-border bg-card px-3.5 text-[13px] font-medium shadow-xs transition-colors duration-[var(--duration-fast)] hover:border-brand/40 disabled:opacity-50"
        >
          {attaching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Paperclip className="h-3.5 w-3.5" />}
          {attaching ? "Reading…" : "Attach"}
        </button>
      </div>

      {documents.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border p-5 text-[13px] leading-relaxed text-muted-foreground">
          Nothing attached. Markdown and plain text need no extra dependency; PDF and .docx are read when
          their parsers are installed.
        </p>
      ) : (
        <ul className="grid gap-2.5 md:grid-cols-2">
          {documents.map((document) => (
            <li
              key={document.name}
              className="flex items-start gap-3 rounded-xl border border-border bg-card p-3.5 shadow-xs"
            >
              <FileText className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13.5px] font-medium">{document.name}</p>
                <p className="tabular mt-0.5 text-[11.5px] text-muted-foreground">
                  {formatCount(document.chars)} characters · {formatCount(document.chunks)} retrievable{" "}
                  {document.chunks === 1 ? "passage" : "passages"}
                </p>
                {document.preview && (
                  <p className="mt-1.5 truncate text-[12px] italic text-muted-foreground">
                    {document.preview}
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={() => onRemove(document.name)}
                disabled={busy === document.name}
                aria-label={`Remove ${document.name}`}
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors duration-[var(--duration-fast)] hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
              >
                {busy === document.name ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Trash2 className="h-3.5 w-3.5" />
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
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
