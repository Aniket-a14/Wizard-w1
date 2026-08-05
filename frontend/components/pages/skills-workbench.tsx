"use client"

import {
  BookmarkPlus,
  FolderOpen,
  Layers,
  Loader2,
  Lock,
  Plus,
  RefreshCw,
  Save,
  Trash2,
} from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { PageHeader } from "@/components/page-header"
import { api, ApiError } from "@/lib/api"
import type { SkillCandidate, SkillDetail, SkillLayer, SkillRoot, SkillSummary } from "@/lib/types"
import { cn } from "@/lib/utils"

const LAYER_ORDER: SkillLayer[] = ["project", "user", "builtin"]

const LAYER_BLURB: Record<SkillLayer, string> = {
  project: "Specific to this checkout. Overrides everything below.",
  user: "Yours, across every project. Where a promoted analysis lands.",
  builtin: "Ships with Wizard. Read-only — an edit here would be lost on update.",
}

const EMPTY_DRAFT = { name: "", description: "", body: "" }

/**
 * Browse, read and edit the agent's know-how.
 *
 * Skills are plain markdown files in three layered directories, so this page is
 * a view onto a filesystem rather than a store of its own — which is why the
 * root paths are shown and why there is a reload button. Editing in a text
 * editor is a supported way to use this feature; the page just has to not
 * contradict it.
 *
 * The built-in layer renders read-only *with its reason*. A disabled control
 * with no explanation is the thing this avoids: the answer to "why can't I edit
 * this" should be on the screen, not in a support conversation.
 */
export function SkillsWorkbench() {
  const [skills, setSkills] = useState<SkillSummary[]>([])
  const [roots, setRoots] = useState<SkillRoot[]>([])
  const [candidates, setCandidates] = useState<SkillCandidate[]>([])
  const [enabled, setEnabled] = useState(true)
  const [selected, setSelected] = useState<SkillDetail | null>(null)
  const [draft, setDraft] = useState(EMPTY_DRAFT)
  const [creating, setCreating] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const payload = await api.skills()
      setSkills(payload.skills)
      setRoots(payload.roots)
      setCandidates(payload.candidates)
      setEnabled(payload.enabled)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not load skills.")
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const open = useCallback(async (name: string) => {
    setError(null)
    setCreating(false)
    try {
      const detail = await api.skill(name)
      setSelected(detail)
      setDraft({ name: detail.name, description: detail.description, body: detail.body })
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not open that skill.")
    }
  }, [])

  const startNew = useCallback(() => {
    setSelected(null)
    setCreating(true)
    setDraft(EMPTY_DRAFT)
    setError(null)
  }, [])

  const save = useCallback(async () => {
    setBusy("save")
    setError(null)
    try {
      const saved = creating
        ? await api.createSkill({ name: draft.name, description: draft.description, body: draft.body })
        : await api.updateSkill(draft.name, { description: draft.description, body: draft.body })
      setSelected(saved)
      setCreating(false)
      setNotice(`Saved “${saved.name}”.`)
      await refresh()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not save.")
    } finally {
      setBusy(null)
    }
  }, [creating, draft, refresh])

  const remove = useCallback(
    async (name: string) => {
      setBusy(`delete:${name}`)
      setError(null)
      try {
        await api.deleteSkill(name)
        setSelected(null)
        setNotice(`Removed “${name}”.`)
        await refresh()
      } catch (cause) {
        setError(cause instanceof ApiError ? cause.message : "Could not remove that skill.")
      } finally {
        setBusy(null)
      }
    },
    [refresh],
  )

  const reload = useCallback(async () => {
    setBusy("reload")
    try {
      const result = await api.reloadSkills()
      setNotice(result.message)
      await refresh()
      if (selected) await open(selected.name)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not reload.")
    } finally {
      setBusy(null)
    }
  }, [open, refresh, selected])

  const dismissCandidate = useCallback(
    async (id: number) => {
      try {
        await api.dismissSkillCandidate(id)
      } finally {
        await refresh()
      }
    },
    [refresh],
  )

  const promote = useCallback(
    async (candidate: SkillCandidate) => {
      setError(null)
      try {
        const drafted = await api.skillDraft(candidate.id)
        setSelected(null)
        setCreating(true)
        setDraft({ name: drafted.name, description: drafted.description, body: drafted.body })
      } catch (cause) {
        setError(cause instanceof ApiError ? cause.message : "Could not build a draft.")
      }
    },
    [],
  )

  const editable = creating || (selected?.writable ?? false)

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <PageHeader
        eyebrow="Skills"
        title="What the agent knows how to do"
        description="Reusable know-how in plain markdown, layered from this project, your account and what ships with Wizard. The agent retrieves the relevant one before it plans, and names it in the answer."
        actions={
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void reload()}
              disabled={busy === "reload"}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-[12.5px] font-medium transition-colors duration-[var(--duration-fast)] hover:bg-muted disabled:opacity-60"
            >
              {busy === "reload" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              Reload from disk
            </button>
            <button
              type="button"
              onClick={startNew}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[linear-gradient(120deg,var(--brand),var(--brand-2))] px-3 py-2 text-[12.5px] font-medium text-brand-foreground shadow-brand transition-all duration-[var(--duration-fast)] hover:brightness-105"
            >
              <Plus className="h-3.5 w-3.5" />
              New skill
            </button>
          </div>
        }
      />

      <div className="flex-1 px-6 py-6 md:px-9">
        {!enabled && (
          <Banner tone="warning">
            Skills are switched off on this deployment (<code>SKILLS_ENABLED=False</code>), so nothing
            here reaches the agent.
          </Banner>
        )}
        {error && <Banner tone="danger">{error}</Banner>}
        {notice && !error && <Banner tone="ok">{notice}</Banner>}

        {candidates.length > 0 && (
          <section className="mb-6">
            <SectionTitle icon={BookmarkPlus}>Worth saving</SectionTitle>
            <div className="space-y-2">
              {candidates.map((candidate) => (
                <div
                  key={candidate.id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card p-3.5 shadow-xs"
                >
                  <div className="min-w-0">
                    <p className="text-[13.5px] font-medium">{candidate.label}</p>
                    <p className="mt-0.5 truncate text-[12px] italic text-muted-foreground">
                      “{candidate.instruction}” — {candidate.occurrences} times
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => void promote(candidate)}
                      className="rounded-lg border border-brand/40 px-2.5 py-1.5 text-[12px] font-medium text-brand transition-colors duration-[var(--duration-fast)] hover:bg-brand/5"
                    >
                      Review and save
                    </button>
                    <button
                      type="button"
                      onClick={() => void dismissCandidate(candidate.id)}
                      className="rounded-lg border border-border px-2.5 py-1.5 text-[12px] transition-colors duration-[var(--duration-fast)] hover:bg-muted"
                    >
                      Not this one
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        <div className="grid gap-6 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
          <div className="space-y-5">
            {LAYER_ORDER.map((layer) => {
              const root = roots.find((entry) => entry.layer === layer)
              const inLayer = skills.filter((skill) => skill.layer === layer)
              return (
                <section key={layer}>
                  <SectionTitle icon={layer === "builtin" ? Lock : Layers}>
                    {root?.label ?? layer}
                  </SectionTitle>
                  <p className="mb-2 text-[11.5px] leading-snug text-muted-foreground">
                    {LAYER_BLURB[layer]}
                  </p>
                  {root && (
                    <p
                      className="mb-2 flex items-start gap-1.5 break-all font-mono text-[10.5px] leading-snug text-muted-foreground/80"
                      title={root.path}
                    >
                      <FolderOpen className="mt-0.5 h-3 w-3 shrink-0" />
                      {root.path}
                    </p>
                  )}
                  {inLayer.length === 0 ? (
                    <p className="rounded-lg border border-dashed border-border px-3 py-2.5 text-[12px] text-muted-foreground">
                      Nothing here yet.
                    </p>
                  ) : (
                    <ul className="space-y-1.5">
                      {inLayer.map((skill) => (
                        <li key={`${skill.layer}-${skill.name}`}>
                          <button
                            type="button"
                            onClick={() => void open(skill.name)}
                            disabled={Boolean(skill.shadowed_by)}
                            className={cn(
                              "w-full rounded-lg border px-3 py-2.5 text-left transition-colors duration-[var(--duration-fast)]",
                              selected?.name === skill.name && selected.layer === skill.layer
                                ? "border-brand/45 bg-brand/5"
                                : "border-border bg-card hover:border-brand/30 hover:bg-accent/40",
                              skill.shadowed_by && "opacity-55",
                            )}
                          >
                            <span className="block truncate font-mono text-[12.5px] font-medium">
                              {skill.name}
                            </span>
                            <span className="mt-0.5 block truncate text-[11.5px] text-muted-foreground">
                              {skill.description}
                            </span>
                            {skill.uses > 0 && (
                              <span className="mt-1 block text-[11px] text-muted-foreground/80">
                                Informed {skill.uses} {skill.uses === 1 ? "analysis" : "analyses"}
                              </span>
                            )}
                            {skill.shadowed_by && (
                              <span className="mt-1 block text-[11px] text-warning">
                                Overridden by the {skill.shadowed_by} copy — that one is what the
                                agent reads.
                              </span>
                            )}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              )
            })}
          </div>

          <div className="min-w-0">
            {!selected && !creating ? (
              <div className="rounded-xl border border-dashed border-border p-8 text-center">
                <p className="text-[13.5px] text-muted-foreground">
                  Pick a skill to read it, or write a new one.
                </p>
                <p className="mx-auto mt-2 max-w-md text-[12px] leading-relaxed text-muted-foreground">
                  A skill is frontmatter and instructions. It never carries executable files — code it
                  suggests is written by the agent and sandboxed like anything else it runs.
                </p>
              </div>
            ) : (
              <div className="rounded-xl border border-border bg-card p-5 shadow-xs">
                {selected && !selected.writable && (
                  <Banner tone="warning">
                    This one ships with Wizard, so it is read-only — an edit would be lost on the next
                    update. Save a skill with the same name to override it; yours takes precedence.
                  </Banner>
                )}

                <div className="space-y-3">
                  <Field label="Name">
                    <input
                      value={draft.name}
                      onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                      disabled={!creating}
                      placeholder="cohort-analysis"
                      className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-[13px] outline-none focus:border-brand/50 disabled:opacity-70"
                    />
                  </Field>
                  <Field label="What it is for">
                    <input
                      value={draft.description}
                      onChange={(event) => setDraft({ ...draft, description: event.target.value })}
                      disabled={!editable}
                      placeholder="How to define cohorts and compute retention"
                      className="w-full rounded-lg border border-border bg-background px-3 py-2 text-[13px] outline-none focus:border-brand/50 disabled:opacity-70"
                    />
                  </Field>
                  <Field label="Instructions">
                    <textarea
                      value={draft.body}
                      onChange={(event) => setDraft({ ...draft, body: event.target.value })}
                      disabled={!editable}
                      rows={22}
                      placeholder="## When to use this&#10;&#10;..."
                      className="w-full resize-y rounded-lg border border-border bg-background px-3 py-2 font-mono text-[12px] leading-relaxed outline-none focus:border-brand/50 disabled:opacity-70"
                    />
                  </Field>
                </div>

                {/* "See which analyses used which skill" — the browser half of
                    it. The live `skill` frame answers this during a turn, and is
                    gone by the time anyone opens this page, so it is read back
                    from what was recorded rather than inferred. */}
                {selected && selected.recent_uses.length > 0 && (
                  <div className="mt-4 rounded-lg border border-border bg-background/60 p-3">
                    <p className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                      Analyses this informed
                    </p>
                    <ul className="space-y-1">
                      {selected.recent_uses.map((use, index) => (
                        <li
                          key={`${index}-${use.timestamp}`}
                          className="flex items-baseline justify-between gap-3 text-[12px] leading-snug"
                        >
                          <span className="min-w-0 flex-1 truncate" title={use.instruction}>
                            {use.instruction || "—"}
                          </span>
                          <span className="shrink-0 text-[11px] text-muted-foreground/70">
                            {new Date(use.timestamp * 1000).toLocaleDateString()}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {selected && (
                  <p
                    className="mt-3 break-all font-mono text-[10.5px] text-muted-foreground/80"
                    title={selected.path}
                  >
                    {selected.path}
                  </p>
                )}

                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void save()}
                    disabled={!editable || busy === "save"}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-[linear-gradient(120deg,var(--brand),var(--brand-2))] px-3.5 py-2 text-[12.5px] font-medium text-brand-foreground shadow-brand transition-all duration-[var(--duration-fast)] hover:brightness-105 disabled:opacity-50"
                  >
                    {busy === "save" ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Save className="h-3.5 w-3.5" />
                    )}
                    {creating ? "Create skill" : "Save changes"}
                  </button>
                  {selected?.writable && (
                    <button
                      type="button"
                      onClick={() => void remove(selected.name)}
                      disabled={busy === `delete:${selected.name}`}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-destructive/30 px-3.5 py-2 text-[12.5px] font-medium text-destructive transition-colors duration-[var(--duration-fast)] hover:bg-destructive/5 disabled:opacity-60"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Delete
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      setSelected(null)
                      setCreating(false)
                      setError(null)
                    }}
                    className="rounded-lg border border-border px-3.5 py-2 text-[12.5px] transition-colors duration-[var(--duration-fast)] hover:bg-muted"
                  >
                    Close
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function SectionTitle({ icon: Icon, children }: { icon: React.ElementType; children: React.ReactNode }) {
  return (
    <h2 className="mb-1.5 flex items-center gap-1.5 font-mono text-[10.5px] uppercase tracking-[0.14em] text-brand">
      <Icon className="h-3 w-3" />
      {children}
    </h2>
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

function Banner({ tone, children }: { tone: "ok" | "warning" | "danger"; children: React.ReactNode }) {
  return (
    <div
      className={cn(
        "mb-4 rounded-xl border p-3 text-[12.5px] leading-relaxed",
        tone === "ok" && "border-success/25 bg-success/8 text-success",
        tone === "warning" && "border-warning/25 bg-warning/8 text-warning",
        tone === "danger" && "border-destructive/25 bg-destructive/8 text-destructive",
      )}
    >
      {children}
    </div>
  )
}
