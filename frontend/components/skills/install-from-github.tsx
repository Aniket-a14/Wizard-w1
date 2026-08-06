"use client"

import { AlertTriangle, Check, Download, GitCommit, Key, Loader2, X } from "lucide-react"
import { useCallback, useState } from "react"

import { api, ApiError } from "@/lib/api"
import type { PendingSkill, SkillRegistryStatus } from "@/lib/types"
import { cn } from "@/lib/utils"

/**
 * Add a skill from a GitHub repository or gist.
 *
 * The shape of this panel is the milestone's security argument made visible.
 * Fetching and installing are two separate acts with the contents in between:
 * pasting a URL stages the skill and shows every character of it next to the
 * exact commit it came from, and only then is there a button that installs it.
 * Nothing here can put a skill in front of the agent without that step.
 *
 * The commit is shown in full rather than abbreviated in a tooltip. "Pinned to
 * this commit, and it will not change until you update it" is the promise being
 * made, and a promise about a specific commit that does not show the commit is
 * asking to be taken on faith.
 */
export function InstallFromGitHub({
  pending,
  registry,
  onChanged,
}: {
  pending: PendingSkill[]
  registry: SkillRegistryStatus | null
  onChanged: () => Promise<void> | void
}) {
  const [url, setUrl] = useState("")
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [showToken, setShowToken] = useState(false)
  const [token, setToken] = useState("")
  const [expanded, setExpanded] = useState<string | null>(null)

  const fetchSource = useCallback(async () => {
    if (!url.trim()) return
    setBusy("fetch")
    setError(null)
    setNotice(null)
    try {
      const result = await api.previewSkillInstall(url.trim())
      setNotice(result.message)
      setExpanded(result.pending[0]?.id ?? null)
      setUrl("")
      await onChanged()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not fetch that source.")
    } finally {
      setBusy(null)
    }
  }, [onChanged, url])

  const approve = useCallback(
    async (item: PendingSkill) => {
      setBusy(`approve:${item.id}`)
      setError(null)
      try {
        const installed = await api.approvePendingSkill(item.id)
        setNotice(`Installed “${installed.name}”, pinned to ${item.short_sha}.`)
        await onChanged()
      } catch (cause) {
        setError(cause instanceof ApiError ? cause.message : "Could not install that skill.")
      } finally {
        setBusy(null)
      }
    },
    [onChanged],
  )

  const discard = useCallback(
    async (item: PendingSkill) => {
      setBusy(`discard:${item.id}`)
      // Cleared here as it is in `fetchSource` and `approve`. The notice below
      // renders only when `error` is null, so a stale failure would both stay on
      // screen and swallow the success message for the action that just worked.
      setError(null)
      try {
        await api.discardPendingSkill(item.id)
        setNotice(`Discarded “${item.name}”. Nothing was installed.`)
        await onChanged()
      } catch (cause) {
        setError(cause instanceof ApiError ? cause.message : "Could not discard that.")
      } finally {
        setBusy(null)
      }
    },
    [onChanged],
  )

  const saveToken = useCallback(async () => {
    setBusy("token")
    setError(null)
    try {
      const result = await api.setGitHubToken(token)
      setNotice(result.message)
      setToken("")
      setShowToken(false)
      await onChanged()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not save the token.")
    } finally {
      setBusy(null)
    }
  }, [onChanged, token])

  return (
    <section className="mb-6 rounded-xl border border-border bg-card p-4 shadow-xs">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-1.5 font-mono text-[10.5px] uppercase tracking-[0.14em] text-brand">
            <Download className="h-3 w-3" />
            Add from GitHub
          </h2>
          <p className="mt-1 max-w-2xl text-[12px] leading-relaxed text-muted-foreground">
            Paste a repository or gist URL. Wizard pins it to the commit it fetched and shows you
            everything in it before anything is installed — a skill is instruction text, and it never
            carries executable files.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowToken((open) => !open)}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-[11.5px] transition-colors duration-[var(--duration-fast)] hover:bg-muted"
        >
          <Key className="h-3 w-3" />
          {registry?.token_saved ? "Token saved" : "Add token"}
        </button>
      </div>

      {showToken && (
        <div className="mb-3 rounded-lg border border-border bg-background/60 p-3">
          <p className="mb-2 text-[11.5px] leading-relaxed text-muted-foreground">
            Optional. Without one GitHub allows 60 requests an hour and no private repositories. It is
            stored on this machine with your other credentials and is never sent anywhere but GitHub.
          </p>
          <div className="flex flex-wrap gap-2">
            <input
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder={registry?.token_saved ? "A token is saved — type a new one to replace it" : "ghp_…"}
              className="min-w-0 flex-1 rounded-lg border border-border bg-background px-3 py-2 font-mono text-[12px] outline-none focus:border-brand/50"
            />
            <button
              type="button"
              onClick={() => void saveToken()}
              disabled={busy === "token"}
              className="rounded-lg border border-border px-3 py-2 text-[12px] transition-colors duration-[var(--duration-fast)] hover:bg-muted disabled:opacity-60"
            >
              {token.trim() ? "Save" : "Clear stored token"}
            </button>
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <input
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void fetchSource()
          }}
          placeholder="https://github.com/owner/repo  ·  owner/repo@v1.2  ·  a gist URL"
          className="min-w-0 flex-1 rounded-lg border border-border bg-background px-3 py-2 font-mono text-[12.5px] outline-none focus:border-brand/50"
        />
        <button
          type="button"
          onClick={() => void fetchSource()}
          disabled={!url.trim() || busy === "fetch"}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[linear-gradient(120deg,var(--brand),var(--brand-2))] px-3.5 py-2 text-[12.5px] font-medium text-brand-foreground shadow-brand transition-all duration-[var(--duration-fast)] hover:brightness-105 disabled:opacity-50"
        >
          {busy === "fetch" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
          Fetch and review
        </button>
      </div>

      {error && (
        <p className="mt-3 rounded-lg border border-destructive/25 bg-destructive/8 p-2.5 text-[12px] leading-relaxed text-destructive">
          {error}
        </p>
      )}
      {notice && !error && (
        <p className="mt-3 rounded-lg border border-success/25 bg-success/8 p-2.5 text-[12px] text-success">
          {notice}
        </p>
      )}

      {pending.length > 0 && (
        <div className="mt-4 space-y-3">
          <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
            Waiting for review — not installed, and not reachable by the agent
          </p>
          {pending.map((item) => (
            <PendingCard
              key={item.id}
              item={item}
              open={expanded === item.id}
              onToggle={() => setExpanded(expanded === item.id ? null : item.id)}
              onApprove={() => void approve(item)}
              onDiscard={() => void discard(item)}
              busy={busy}
            />
          ))}
        </div>
      )}
    </section>
  )
}

function PendingCard({
  item,
  open,
  onToggle,
  onApprove,
  onDiscard,
  busy,
}: {
  item: PendingSkill
  open: boolean
  onToggle: () => void
  onApprove: () => void
  onDiscard: () => void
  busy: string | null
}) {
  return (
    <div className="rounded-xl border border-warning/30 bg-warning/[0.04] p-3.5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono text-[13px] font-medium">{item.name}</p>
          <p className="mt-0.5 text-[12px] text-muted-foreground">{item.description}</p>
          <p className="mt-1.5 flex flex-wrap items-center gap-1.5 break-all font-mono text-[10.5px] text-muted-foreground/85">
            <GitCommit className="h-3 w-3 shrink-0" />
            {item.source.url}
            <span className="text-muted-foreground/60">@</span>
            <span title={item.sha}>{item.sha}</span>
          </p>
        </div>
        <button
          type="button"
          onClick={onToggle}
          className="shrink-0 rounded-lg border border-border px-2.5 py-1.5 text-[11.5px] transition-colors duration-[var(--duration-fast)] hover:bg-muted"
        >
          {open ? "Hide contents" : `Read all ${item.chars.toLocaleString()} characters`}
        </button>
      </div>

      {item.conflicts_with && (
        <p className="mt-2.5 flex items-start gap-1.5 rounded-lg border border-warning/30 bg-warning/8 p-2.5 text-[11.5px] leading-relaxed text-warning">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            A {item.conflict_layer} skill called <code>{item.conflicts_with}</code> already exists.
            {item.conflict_layer === "project"
              ? " That one takes precedence, so this copy would not be the one the agent reads."
              : " Installing this replaces it."}
          </span>
        </p>
      )}

      {open && (
        <pre className="mt-3 max-h-[26rem] overflow-auto rounded-lg border border-border bg-background p-3 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap">
          {item.body}
        </pre>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onApprove}
          disabled={busy === `approve:${item.id}`}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-lg border border-brand/40 px-3 py-1.5 text-[12px] font-medium text-brand",
            "transition-colors duration-[var(--duration-fast)] hover:bg-brand/5 disabled:opacity-60",
          )}
        >
          {busy === `approve:${item.id}` ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Check className="h-3.5 w-3.5" />
          )}
          Install at {item.short_sha}
        </button>
        <button
          type="button"
          onClick={onDiscard}
          disabled={busy === `discard:${item.id}`}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[12px] transition-colors duration-[var(--duration-fast)] hover:bg-muted disabled:opacity-60"
        >
          <X className="h-3.5 w-3.5" />
          Discard
        </button>
      </div>
    </div>
  )
}

/**
 * The update flow for an installed skill: what changed, then whether to take it.
 *
 * The diff comes back from a call that writes nothing, and applying it is a
 * second call. "Pin, don't track" is only true if there is a moment where the
 * user has seen the change and the file has not moved yet.
 */
export function UpdateFromSource({
  skill,
  onUpdated,
}: {
  skill: { name: string; source_url: string | null; source_ref: string | null; pinned_sha: string | null; updated_at: number | null }
  onUpdated: () => Promise<void> | void
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<{ changed: boolean; diff: string; message: string } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const check = useCallback(async () => {
    setBusy("check")
    setError(null)
    try {
      setResult(await api.updateSkillFromSource(skill.name, false))
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not check for an update.")
    } finally {
      setBusy(null)
    }
  }, [skill.name])

  const apply = useCallback(async () => {
    setBusy("apply")
    setError(null)
    try {
      const applied = await api.updateSkillFromSource(skill.name, true)
      setResult({ changed: false, diff: "", message: applied.message })
      await onUpdated()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not apply the update.")
    } finally {
      setBusy(null)
    }
  }, [onUpdated, skill.name])

  if (!skill.source_url) return null

  return (
    <div className="mt-4 rounded-lg border border-border bg-background/60 p-3">
      <p className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
        Installed from
      </p>
      <p className="break-all font-mono text-[11px] leading-snug">
        <a
          href={skill.source_url}
          target="_blank"
          rel="noreferrer noopener"
          className="text-brand hover:underline"
        >
          {skill.source_url}
        </a>
      </p>
      <p className="mt-1 break-all font-mono text-[10.5px] text-muted-foreground/85">
        pinned to {skill.pinned_sha}
        {skill.source_ref ? ` · following ${skill.source_ref}` : " · following the default branch"}
        {skill.updated_at ? ` · last changed ${new Date(skill.updated_at * 1000).toLocaleDateString()}` : ""}
      </p>
      <p className="mt-1.5 text-[11.5px] leading-relaxed text-muted-foreground">
        It stays at this commit until you update it — a pulled skill never changes under you.
      </p>

      <div className="mt-2.5 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void check()}
          disabled={busy === "check"}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-[12px] transition-colors duration-[var(--duration-fast)] hover:bg-muted disabled:opacity-60"
        >
          {busy === "check" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Check for an update
        </button>
        {result?.changed && (
          <button
            type="button"
            onClick={() => void apply()}
            disabled={busy === "apply"}
            className="inline-flex items-center gap-1.5 rounded-lg border border-brand/40 px-2.5 py-1.5 text-[12px] font-medium text-brand transition-colors duration-[var(--duration-fast)] hover:bg-brand/5 disabled:opacity-60"
          >
            <Check className="h-3.5 w-3.5" />
            Apply this update
          </button>
        )}
      </div>

      {error && <p className="mt-2 text-[12px] leading-relaxed text-destructive">{error}</p>}
      {result && !error && (
        <div className="mt-2.5">
          <p className="text-[12px] text-muted-foreground">{result.message}</p>
          {result.diff && (
            <pre className="mt-2 max-h-72 overflow-auto rounded-lg border border-border bg-background p-2.5 font-mono text-[11px] leading-relaxed">
              {result.diff}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}
