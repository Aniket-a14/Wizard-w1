import type React from "react"

import { cn } from "@/lib/utils"

/**
 * The masthead every non-chat page opens with.
 *
 * Kept as one component so the eyebrow / title / description rhythm is
 * identical across routes — the fastest way for a multi-page app to start
 * looking assembled rather than designed screen by screen.
 */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  className,
}: {
  eyebrow: string
  title: string
  description?: string
  actions?: React.ReactNode
  className?: string
}) {
  return (
    <header
      className={cn(
        "flex shrink-0 flex-wrap items-end justify-between gap-4 border-b border-border px-6 pb-6",
        // Extra top padding below `md` clears the floating menu button, which
        // sits at top-3 left-3 and would otherwise land on the eyebrow.
        "pt-16 md:px-9 md:pt-10",
        className,
      )}
    >
      <div className="min-w-0">
        <p className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-brand">{eyebrow}</p>
        <h1 className="mt-2.5 text-[clamp(1.6rem,3vw,2.1rem)] font-semibold leading-[1.1] tracking-[-0.035em]">
          {title}
        </h1>
        {description && (
          <p className="mt-2.5 max-w-xl text-pretty text-[14px] leading-relaxed text-muted-foreground">
            {description}
          </p>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  )
}

/** A titled block within a page body. */
export function Section({
  title,
  description,
  children,
  actions,
}: {
  title: string
  description?: string
  children: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <section className="border-b border-border px-6 py-8 last:border-b-0 md:px-9">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold tracking-[-0.015em]">{title}</h2>
          {description && (
            <p className="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-muted-foreground">
              {description}
            </p>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      {children}
    </section>
  )
}
