"use client"

/**
 * Connections — data sources that are not files.
 *
 * A sibling of `ReferenceDocuments`, and shaped like it on purpose: both are
 * ingest surfaces on the same page, because both are just ways of getting
 * something into the session. A table imported here appears in the dataset grid
 * above exactly as an uploaded CSV does.
 *
 * Its own file rather than a fourth component inside `data-workbench.tsx`: it
 * carries a form, a target picker and a write-back confirmation, which is more
 * state than that file's other sections have between them.
 */

import { useCallback, useEffect, useState } from "react"
import { Database, Loader2, PlugZap, Trash2, TriangleAlert } from "lucide-react"

import { api, ApiError } from "@/lib/api"
import type {
  ConnectionSummary,
  ConnectionTarget,
  ConnectorKind,
  DatasetSummary,
} from "@/lib/types"
import { cn } from "@/lib/utils"

export function ConnectionsPanel({
  datasets,
  onImported,
}: {
  /** Session tables, so a write can offer one. Passed in rather than fetched
   *  again: the page already holds them and a second copy would go stale. */
  datasets: DatasetSummary[]
  onImported: () => void
}) {
  const [connections, setConnections] = useState<ConnectionSummary[]>([])
  const [kinds, setKinds] = useState<ConnectorKind[]>([])
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<ConnectionSummary | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [status, setStatus] = useState<Record<string, string>>({})
  const [targets, setTargets] = useState<Record<string, ConnectionTarget[]>>({})
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const body = await api.connections()
      setConnections(body.connections)
      setKinds(body.kinds)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not load connections.")
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const test = async (connection: ConnectionSummary) => {
    setBusy(connection.id)
    try {
      const result = await api.testConnection(connection.id)
      setStatus((current) => ({ ...current, [connection.id]: result.detail }))
    } catch (cause) {
      setStatus((current) => ({
        ...current,
        [connection.id]: cause instanceof ApiError ? cause.message : "Test failed.",
      }))
    } finally {
      setBusy(null)
    }
  }

  const browse = async (connection: ConnectionSummary) => {
    setBusy(connection.id)
    setError(null)
    try {
      const body = await api.connectionSchema(connection.id)
      setTargets((current) => ({ ...current, [connection.id]: body.targets }))
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not read the schema.")
    } finally {
      setBusy(null)
    }
  }

  const importTarget = async (connection: ConnectionSummary, target: string) => {
    setBusy(connection.id)
    setError(null)
    try {
      const result = await api.importFromConnection(connection.id, target)
      setStatus((current) => ({ ...current, [connection.id]: result.message }))
      onImported()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not import that table.")
    } finally {
      setBusy(null)
    }
  }

  const remove = async (connection: ConnectionSummary) => {
    // Deleting a connection also drops every table imported from it and the
    // per-source data policy set on it, and none of that comes back. Enabling
    // write-back — which is reversible — asks for the name typed out, so a
    // silent one-click destructive action here was the odd one out.
    const imported = connection.name
    if (
      !window.confirm(
        `Remove the connection "${imported}"?

` +
          "Any tables imported from it are removed from this session too, along with " +
          "the cloud-data policy set for it. The saved credential is deleted.",
      )
    ) {
      return
    }
    setBusy(connection.id)
    try {
      await api.deleteConnection(connection.id)
      await refresh()
      onImported()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not remove that connection.")
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="border-t border-border px-6 py-6 md:px-9">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-[-0.015em]">
            <Database className="h-3.5 w-3.5 text-brand" />
            Connections
          </h2>
          <p className="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-muted-foreground">
            Databases, document stores and object storage. A table imported here joins the tables above
            and can be analysed alongside them. Every connection is read-only until you say otherwise.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setAdding((open) => !open)}
          className="flex h-9 shrink-0 items-center gap-2 rounded-lg border border-border bg-card px-3.5 text-[13px] font-medium shadow-xs transition-colors duration-[var(--duration-fast)] hover:border-brand/40"
        >
          <PlugZap className="h-3.5 w-3.5" />
          {adding ? "Cancel" : "Add a connection"}
        </button>
      </div>

      {error && (
        <p className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 px-3.5 py-2.5 text-[13px] text-destructive">
          {error}
        </p>
      )}

      {(adding || editing) && (
        <ConnectionForm
          kinds={kinds}
          existing={editing}
          onCancel={() => {
            setAdding(false)
            setEditing(null)
          }}
          onCreated={async () => {
            setAdding(false)
            setEditing(null)
            await refresh()
          }}
        />
      )}

      {connections.length === 0 && !adding ? (
        <p className="rounded-xl border border-dashed border-border p-5 text-[13px] leading-relaxed text-muted-foreground">
          No connections yet. Which databases you can reach depends on which drivers are installed —
          SQLite needs none.
        </p>
      ) : (
        <ul className="grid gap-2.5">
          {connections.map((connection) => (
            <li key={connection.id} className="rounded-xl border border-border bg-card p-3.5 shadow-xs">
              <div className="flex items-start gap-3">
                <Database className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 truncate text-[13.5px] font-medium">
                    {connection.name}
                    {connection.read_only ? (
                      <span className="rounded-md bg-muted px-1.5 py-0.5 text-[10.5px] font-normal text-muted-foreground">
                        Read-only
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 rounded-md bg-amber-500/10 px-1.5 py-0.5 text-[10.5px] font-normal text-amber-700">
                        <TriangleAlert className="h-3 w-3" />
                        Write-back on
                      </span>
                    )}
                  </p>
                  <p className="tabular mt-0.5 text-[11.5px] text-muted-foreground">
                    {connection.kind}
                    {connection.has_secret && " · credential stored"}
                  </p>
                  {!connection.available && (
                    <p className="mt-1.5 text-[12px] text-muted-foreground">
                      The driver for this kind is not installed. Run{" "}
                      <code className="rounded bg-muted px-1 py-0.5">{connection.install_hint}</code>.
                    </p>
                  )}
                  {status[connection.id] && (
                    <p className="mt-1.5 text-[12px] text-muted-foreground">{status[connection.id]}</p>
                  )}
                </div>

                <div className="flex shrink-0 items-center gap-1.5">
                  <SmallButton onClick={() => test(connection)} disabled={busy === connection.id}>
                    Test
                  </SmallButton>
                  <SmallButton
                    onClick={() => {
                      setAdding(false)
                      setEditing(connection)
                    }}
                    disabled={busy === connection.id}
                  >
                    Edit
                  </SmallButton>
                  <SmallButton onClick={() => browse(connection)} disabled={busy === connection.id}>
                    {busy === connection.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      "Browse"
                    )}
                  </SmallButton>
                  <button
                    type="button"
                    onClick={() => remove(connection)}
                    disabled={busy === connection.id}
                    aria-label={`Remove ${connection.name}`}
                    className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors duration-[var(--duration-fast)] hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              {targets[connection.id] && (
                <ul className="mt-3 grid gap-1.5 border-t border-border pt-3 md:grid-cols-2">
                  {targets[connection.id].length === 0 && (
                    <li className="text-[12.5px] text-muted-foreground">Nothing readable found.</li>
                  )}
                  {targets[connection.id].map((target) => (
                    <li key={target.qualified} className="flex items-center justify-between gap-2">
                      <span className="min-w-0 truncate text-[12.5px]">
                        {target.qualified}
                        {target.columns.length > 0 && (
                          <span className="text-muted-foreground"> · {target.columns.length} cols</span>
                        )}
                      </span>
                      <SmallButton
                        onClick={() => importTarget(connection, target.qualified)}
                        disabled={busy === connection.id}
                      >
                        Import
                      </SmallButton>
                    </li>
                  ))}
                </ul>
              )}

              {!connection.read_only && (
                <WriteBackForm connection={connection} datasets={datasets} />
              )}
              <WriteBackControl connection={connection} onChanged={refresh} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function SmallButton({
  children,
  onClick,
  disabled,
}: {
  children: React.ReactNode
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex h-7 items-center rounded-md border border-border px-2.5 text-[12px] font-medium transition-colors duration-[var(--duration-fast)] hover:border-brand/40 disabled:opacity-50"
    >
      {children}
    </button>
  )
}

/**
 * Write-back is deliberately higher-friction than everything else on this page.
 * Turning it on asks for the connection's own name typed back, because it is the
 * only control here whose consequences land outside this machine — and no
 * permission profile can grant it, by design.
 */
function WriteBackControl({
  connection,
  onChanged,
}: {
  connection: ConnectionSummary
  onChanged: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [confirm, setConfirm] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const apply = async (enable: boolean) => {
    setBusy(true)
    setError(null)
    try {
      await api.setWriteBack(connection.id, enable, confirm)
      setOpen(false)
      setConfirm("")
      await onChanged()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not change write-back.")
    } finally {
      setBusy(false)
    }
  }

  if (!connection.read_only) {
    return (
      <div className="mt-3 flex items-center justify-between gap-2 border-t border-border pt-3">
        <p className="text-[12px] text-amber-700">
          This connection can be written to. The agent still asks every time.
        </p>
        <SmallButton onClick={() => apply(false)} disabled={busy}>
          Make read-only
        </SmallButton>
      </div>
    )
  }

  return (
    <div className="mt-3 border-t border-border pt-3">
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="text-[12px] text-muted-foreground underline-offset-2 hover:underline"
        >
          Enable write-back…
        </button>
      ) : (
        <div className="grid gap-2">
          <p className="text-[12px] leading-relaxed text-muted-foreground">
            This lets an analysis modify data in <strong>{connection.name}</strong>. Type the
            connection&rsquo;s name to confirm.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              placeholder={connection.name}
              aria-label="Type the connection name to confirm"
              className="h-8 min-w-0 flex-1 rounded-md border border-border bg-background px-2.5 text-[12.5px]"
            />
            <SmallButton onClick={() => apply(true)} disabled={busy || confirm !== connection.name}>
              Enable
            </SmallButton>
            <SmallButton
              onClick={() => {
                setOpen(false)
                setConfirm("")
              }}
              disabled={busy}
            >
              Cancel
            </SmallButton>
          </div>
          {error && <p className="text-[12px] text-destructive">{error}</p>}
        </div>
      )}
    </div>
  )
}

/**
 * Writing a session table back to the source.
 *
 * Only rendered once write-back is enabled for the connection, because until
 * then the backend refuses without asking anything — offering a control whose
 * only outcome is a refusal is worse than not offering it.
 */
function WriteBackForm({
  connection,
  datasets,
}: {
  connection: ConnectionSummary
  datasets: DatasetSummary[]
}) {
  const [dataset, setDataset] = useState("")
  const [target, setTarget] = useState("")
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<string | null>(null)

  const send = async () => {
    setBusy(true)
    setResult(null)
    try {
      const body = await api.writeToConnection(connection.id, dataset, target)
      setResult(body.detail)
    } catch (cause) {
      setResult(cause instanceof ApiError ? cause.message : "The write failed.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-3 grid gap-2 border-t border-border pt-3">
      <p className="text-[12px] text-muted-foreground">Write a table back to this source.</p>
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={dataset}
          onChange={(event) => setDataset(event.target.value)}
          aria-label="Table to write"
          className="h-8 min-w-0 flex-1 rounded-md border border-border bg-background px-2 text-[12.5px]"
        >
          <option value="">Choose a table…</option>
          {datasets.map((entry) => (
            <option key={entry.name} value={entry.name}>
              {entry.name}
            </option>
          ))}
        </select>
        <input
          value={target}
          onChange={(event) => setTarget(event.target.value)}
          placeholder="destination table"
          aria-label="Destination table"
          className="h-8 min-w-0 flex-1 rounded-md border border-border bg-background px-2.5 text-[12.5px]"
        />
        <SmallButton onClick={send} disabled={busy || !dataset || !target.trim()}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Write"}
        </SmallButton>
      </div>
      {result && <p className="text-[12px] text-muted-foreground">{result}</p>}
    </div>
  )
}

function ConnectionForm({
  kinds,
  existing,
  onCancel,
  onCreated,
}: {
  kinds: ConnectorKind[]
  /** Present when editing. The same form both ways — an edit screen that drifts
   *  from the create screen is two places to add a field to. */
  existing?: ConnectionSummary | null
  onCancel: () => void
  onCreated: () => Promise<void>
}) {
  const [name, setName] = useState(existing?.name ?? "")
  // Not seeded from `kinds[0]` at mount: `kinds` arrives asynchronously, so a
  // form opened first would snapshot "" and never recover — the select would
  // display the first option while state held nothing, rendering no fields and
  // leaving Save disabled. `null` means "not chosen yet"; the effective kind is
  // derived below, so it follows `kinds` until the user actually picks one.
  const [chosenKind, setChosenKind] = useState<string | null>(existing?.kind ?? null)
  const [options, setOptions] = useState<Record<string, string>>(existing?.options ?? {})
  const [secret, setSecret] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const kind = chosenKind ?? kinds[0]?.kind ?? ""
  const selected = kinds.find((entry) => entry.kind === kind)

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const body = {
        name,
        kind,
        // Empty fields are dropped rather than stored as "": a blank host and an
        // unset host mean the same thing, and the driver reads them differently.
        options: Object.fromEntries(Object.entries(options).filter(([, value]) => value.trim())),
        // Left out when blank on an edit, which means "keep the stored secret" —
        // not "there is no secret".
        secret: secret || undefined,
      }
      await (existing ? api.updateConnection(existing.id, body) : api.createConnection(body))
      await onCreated()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not save the connection.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mb-4 grid gap-3 rounded-xl border border-border bg-card p-4 shadow-xs">
      <div className="grid gap-2 md:grid-cols-2">
        <label className="grid gap-1">
          <span className="text-[11.5px] text-muted-foreground">Name</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Warehouse"
            className="h-8 rounded-md border border-border bg-background px-2.5 text-[12.5px]"
          />
        </label>
        <label className="grid gap-1">
          <span className="text-[11.5px] text-muted-foreground">Kind</span>
          <select
            value={kind}
            onChange={(event) => {
              setChosenKind(event.target.value)
              setOptions({})
            }}
            className="h-8 rounded-md border border-border bg-background px-2 text-[12.5px]"
          >
            {kinds.map((entry) => (
              <option key={entry.kind} value={entry.kind}>
                {entry.label}
                {!entry.available && " (driver not installed)"}
              </option>
            ))}
          </select>
        </label>
      </div>

      {selected && (
        <>
          <p className="text-[12px] leading-relaxed text-muted-foreground">{selected.description}</p>
          {!selected.available && (
            <p className="text-[12px] text-muted-foreground">
              Install the driver first:{" "}
              <code className="rounded bg-muted px-1 py-0.5">{selected.install_hint}</code>
            </p>
          )}
          <div className="grid gap-2 md:grid-cols-3">
            {selected.fields.map((field) => (
              <label key={field} className="grid gap-1">
                <span className="text-[11.5px] text-muted-foreground">{field}</span>
                <input
                  value={options[field] ?? ""}
                  onChange={(event) =>
                    setOptions((current) => ({ ...current, [field]: event.target.value }))
                  }
                  className="h-8 rounded-md border border-border bg-background px-2.5 text-[12.5px]"
                />
              </label>
            ))}
            <label className="grid gap-1">
              <span className="text-[11.5px] text-muted-foreground">
                secret {selected.requires_secret ? "" : "(optional)"}
              </span>
              <input
                type="password"
                value={secret}
                onChange={(event) => setSecret(event.target.value)}
                className="h-8 rounded-md border border-border bg-background px-2.5 text-[12.5px]"
              />
            </label>
          </div>
        </>
      )}

      <p className="text-[11.5px] leading-relaxed text-muted-foreground">
        The secret is stored on this machine only, in your Wizard config directory, and is never sent
        anywhere but the data source itself.
        {existing?.has_secret && " Leave it blank to keep the one already stored."}
        {" A password inside a pasted connection string is moved into that store too, so it is never written to the connections file."}
      </p>

      {error && <p className="text-[12px] text-destructive">{error}</p>}

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={submit}
          disabled={busy || !name.trim() || !kind}
          className={cn(
            "flex h-8 items-center gap-2 rounded-md bg-brand px-3 text-[12.5px] font-medium text-brand-foreground",
            "transition-opacity duration-[var(--duration-fast)] disabled:opacity-50",
          )}
        >
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {existing ? "Save changes" : "Save connection"}
        </button>
        <SmallButton onClick={onCancel} disabled={busy}>
          Cancel
        </SmallButton>
      </div>
    </div>
  )
}
