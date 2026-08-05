"use client"

import { Lightbulb } from "lucide-react"
import Link from "next/link"

import type { SkillUse } from "@/lib/types"

const LAYER_LABEL: Record<string, string> = {
  builtin: "built-in",
  user: "yours",
  project: "project",
}

/**
 * Which skills informed the answer above.
 *
 * This is Milestone 5's first acceptance criterion made visible: "the agent can
 * name which skill informed a decision". Without it the claim would be true only
 * inside a prompt nobody sees.
 *
 * Deliberately one quiet line rather than a panel. It sits with the trust
 * surfaces because it answers the same question they do — where did this come
 * from — and each name links to the file so "which skill?" and "what does it
 * say?" are one click apart.
 */
export function SkillCredit({ skills }: { skills: SkillUse[] }) {
  if (skills.length === 0) return null

  return (
    <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[11.5px] text-muted-foreground">
      <Lightbulb className="h-3 w-3 shrink-0 text-brand" aria-hidden="true" />
      <span>Informed by</span>
      {skills.map((skill, index) => (
        <span key={skill.name} className="inline-flex items-center gap-1.5">
          <Link
            href="/skills"
            title={skill.description || `Open the ${skill.name} skill`}
            className="rounded font-medium text-foreground underline decoration-border underline-offset-2 transition-colors duration-[var(--duration-fast)] hover:decoration-brand"
          >
            {skill.name}
          </Link>
          <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground/70">
            {LAYER_LABEL[skill.layer] ?? skill.layer}
          </span>
          {index < skills.length - 1 && <span aria-hidden="true">·</span>}
        </span>
      ))}
    </div>
  )
}
