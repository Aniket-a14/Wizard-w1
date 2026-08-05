"use client"

import { BookmarkPlus, Loader2 } from "lucide-react"
import { useState } from "react"

import { api, ApiError } from "@/lib/api"
import type { SkillCandidate } from "@/lib/types"

/**
 * "You have run this analysis three times — save it as a skill?"
 *
 * The promotion pipeline's user-facing half. Nothing is written until the form
 * is submitted: the backend counts recurrences and emits an offer, and this is
 * the only thing that turns one into a file. That separation is the milestone's
 * "not auto-published silently", enforced rather than promised.
 *
 * The draft is fetched rather than composed here, and it is built from the plan
 * and code that actually ran — so this is a confirmation, not a writing task.
 * Declining is persisted server-side, so it is not asked again next turn.
 *
 * **Two ways in, one form.** The milestone lists them separately: an offer the
 * agent makes once a question recurs (`candidate` set), and an explicit "save
 * this one" about the answer already on screen (`instruction` set, no
 * threshold). They differ only in what fetches the draft and whether declining
 * is worth recording — so they are one component, not two that drift.
 */
export function SkillPromotion({
  candidate,
  instruction,
  onSettled,
}: {
  candidate?: SkillCandidate | null
  instruction?: string
  onSettled: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState(candidate?.suggested_name ?? "")
  const [description, setDescription] = useState("")
  const [body, setBody] = useState("")
  const [candidateId, setCandidateId] = useState<number | null>(candidate?.id ?? null)

  const question = candidate?.instruction ?? instruction ?? ""

  async function openForm() {
    setBusy(true)
    setError(null)
    try {
      const draft = candidate
        ? await api.skillDraft(candidate.id)
        : await api.skillDraftFor(question)
      setName(draft.name)
      setDescription(draft.description)
      setBody(draft.body)
      if (!candidate) setCandidateId(draft.candidate_id ?? null)
      setExpanded(true)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not build a draft.")
    } finally {
      setBusy(false)
    }
  }

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await api.createSkill({ name, description, body, candidate_id: candidateId })
      onSettled()
    } catch (cause) {
      // The candidate is settled server-side only after the file exists, so a
      // rejected name leaves the offer standing rather than consuming it.
      setError(cause instanceof ApiError ? cause.message : "Could not save the skill.")
      setBusy(false)
    }
  }

  async function dismiss() {
    // Only an offer the agent made is worth recording a refusal to. Backing out
    // of a form you opened yourself is not a decision about the analysis.
    if (!candidate) {
      onSettled()
      return
    }

    setBusy(true)
    setError(null)
    try {
      await api.dismissSkillCandidate(candidate.id)
      onSettled()
    } catch (cause) {
      // The decline is persisted server-side, so a failed call means it was not
      // recorded. Closing the card anyway would report a decision that did not
      // happen — and since the offer is emitted once, at the threshold, it would
      // not come back in chat to correct the impression.
      setError(cause instanceof ApiError ? cause.message : "Could not record that. Try again.")
      setBusy(false)
    }
  }

  return (
    <div className="ring-gradient mt-3 rounded-xl p-4 shadow-sm">
      <p className="mb-1 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-brand">
        <BookmarkPlus className="h-3 w-3" />
        {candidate ? "Worth saving?" : "Save as skill"}
      </p>
      {candidate ? (
        <p className="text-[14px] leading-relaxed">
          {candidate.label}
          {" — "}
          <span className="text-muted-foreground">
            {candidate.occurrences} times so far. Save it as a skill so the agent starts from it
            next time?
          </span>
        </p>
      ) : (
        <p className="text-[14px] leading-relaxed text-muted-foreground">
          Write this analysis down as know-how the agent starts from next time.
        </p>
      )}
      <p className="mt-1 text-[12px] italic leading-snug text-muted-foreground">“{question}”</p>

      {expanded && (
        <div className="mt-3 space-y-2.5">
          <Field label="Name">
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="w-full rounded-lg border border-border bg-card px-2.5 py-1.5 font-mono text-[12.5px] outline-none focus:border-brand/50"
            />
          </Field>
          <Field label="What it is for">
            <input
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className="w-full rounded-lg border border-border bg-card px-2.5 py-1.5 text-[12.5px] outline-none focus:border-brand/50"
            />
          </Field>
          <Field label="Instructions">
            <textarea
              value={body}
              onChange={(event) => setBody(event.target.value)}
              rows={10}
              className="w-full resize-y rounded-lg border border-border bg-card px-2.5 py-1.5 font-mono text-[12px] leading-relaxed outline-none focus:border-brand/50"
            />
          </Field>
          <p className="text-[11.5px] leading-snug text-muted-foreground">
            Drafted from the plan and code that actually ran. Edit it into something you would want
            to read in six months — it goes in your user skills and applies to every project.
          </p>
        </div>
      )}

      {error && <p className="mt-2 text-[12px] text-destructive">{error}</p>}

      <div className="mt-3 flex gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => void (expanded ? save() : openForm())}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[linear-gradient(120deg,var(--brand),var(--brand-2))] px-3.5 py-2 text-[12.5px] font-medium text-brand-foreground shadow-brand transition-all duration-[var(--duration-fast)] hover:brightness-105 active:scale-[0.985] disabled:opacity-60"
        >
          {busy && <Loader2 className="h-3 w-3 animate-spin" />}
          {expanded ? "Save skill" : "Review and save"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void dismiss()}
          className="rounded-lg border border-border px-3.5 py-2 text-[12.5px] font-medium transition-colors duration-[var(--duration-fast)] hover:bg-muted disabled:opacity-60"
        >
          {candidate ? "Not this one" : "Cancel"}
        </button>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </span>
      {children}
    </label>
  )
}
