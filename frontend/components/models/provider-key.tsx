"use client"

import { Check, ExternalLink, KeyRound, Loader2, Trash2 } from "lucide-react"
import { useState } from "react"

import { api } from "@/lib/api"
import type { ProviderInfo } from "@/lib/types"
import { cn } from "@/lib/utils"

/**
 * Key entry for a cloud provider.
 *
 * The key is written to a file in the platform config directory, owned by this
 * account and readable by nobody else. It is never sent back: what the field
 * shows once saved is a masked tail, because reading a key back to render it
 * would put it in a response, a browser cache and a devtools log for no benefit.
 */
export function ProviderKey({
  provider,
  onChanged,
}: {
  provider: ProviderInfo
  onChanged: () => void
}) {
  const [value, setValue] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!provider.requires_key && !provider.key_stored) return null

  const save = async () => {
    const trimmed = value.trim()
    if (!trimmed) return
    setBusy(true)
    setError(null)
    try {
      await api.setProviderKey(provider.id, trimmed)
      setValue("")
      onChanged()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save the key.")
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.deleteProviderKey(provider.id)
      onChanged()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not remove the key.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <KeyRound className="h-3.5 w-3.5 text-brand" />
        <h3 className="text-[13px] font-semibold tracking-[-0.01em]">{provider.label} API key</h3>
        {provider.has_key && (
          <span className="flex items-center gap-1 rounded-md bg-success/10 px-1.5 py-0.5 text-[10.5px] font-medium text-success">
            <Check className="h-2.5 w-2.5" />
            {provider.key_hint || "set"}
          </span>
        )}
      </div>

      <p className="mt-2 text-[12.5px] leading-relaxed text-muted-foreground">
        Stored on this machine only, readable by your account alone. It is never sent anywhere but{" "}
        {provider.label}, and never read back into this page.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input
          type="password"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void save()
          }}
          placeholder={provider.has_key ? "Replace the stored key…" : "Paste your API key…"}
          aria-label={`${provider.label} API key`}
          autoComplete="off"
          spellCheck={false}
          className="h-9 min-w-0 flex-1 rounded-lg border border-border bg-background px-3 font-mono text-[12.5px] transition-colors duration-[var(--duration-fast)] focus:border-brand/50 focus:outline-none"
        />
        <button
          type="button"
          onClick={() => void save()}
          disabled={busy || !value.trim()}
          className={cn(
            "flex h-9 items-center gap-2 rounded-lg px-3.5 text-[12.5px] font-medium",
            "transition-colors duration-[var(--duration-fast)]",
            value.trim() && !busy
              ? "bg-primary text-primary-foreground hover:opacity-90"
              : "cursor-not-allowed bg-muted text-muted-foreground/60",
          )}
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Save
        </button>
        {provider.key_stored && (
          <button
            type="button"
            onClick={() => void remove()}
            disabled={busy}
            aria-label={`Remove the stored ${provider.label} key`}
            className="flex h-9 w-9 items-center justify-center rounded-lg border border-border text-muted-foreground transition-colors duration-[var(--duration-fast)] hover:border-destructive/40 hover:text-destructive disabled:opacity-40"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {error && <p className="mt-2 text-[12px] text-destructive">{error}</p>}

      {provider.docs_url && (
        <a
          href={provider.docs_url}
          target="_blank"
          rel="noreferrer"
          className="mt-2.5 inline-flex items-center gap-1.5 text-[11.5px] text-muted-foreground transition-colors duration-[var(--duration-fast)] hover:text-foreground"
        >
          Where to get a key
          <ExternalLink className="h-3 w-3" />
        </a>
      )}
    </div>
  )
}
