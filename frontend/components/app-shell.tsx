"use client"

import { Database, Menu, MessagesSquare, Settings2, SlidersHorizontal, X } from "lucide-react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useState } from "react"

import { AnimatedOrb } from "@/components/animated-orb"
import { SoundToggle } from "@/components/sound-toggle"
import { api } from "@/lib/api"
import type { ServerConfig } from "@/lib/types"
import { preloadSounds } from "@/lib/use-sound"
import { cn } from "@/lib/utils"

const NAV = [
  { href: "/", label: "Chat", hint: "Ask, watch, verify", icon: MessagesSquare },
  { href: "/data", label: "Data", hint: "Datasets and preview", icon: Database },
  { href: "/models", label: "Models", hint: "Providers and roles", icon: SlidersHorizontal },
  { href: "/settings", label: "Settings", hint: "Session and diagnostics", icon: Settings2 },
] as const

/**
 * Persistent application chrome.
 *
 * The product has no marketing page — the first thing loaded is the workspace,
 * and the rail is how you move between its surfaces. It renders once in the
 * root layout so navigating between pages never rebuilds it, and the chat
 * WebSocket (owned further down the tree) is not disturbed by a route change.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const [config, setConfig] = useState<ServerConfig | null>(null)
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => {
    preloadSounds()
    void api.config().then(setConfig).catch(() => setConfig(null))
  }, [])

  return (
    <div className="flex h-screen w-full overflow-hidden">
      {/* Without this a keyboard user tabs the whole rail on every page. */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-[70] focus:rounded-lg focus:bg-primary focus:px-3 focus:py-2 focus:text-[13px] focus:font-medium focus:text-primary-foreground focus:shadow-md"
      >
        Skip to content
      </a>

      {mobileOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setMobileOpen(false)}
          className="fixed inset-0 z-40 bg-foreground/15 backdrop-blur-[3px] md:hidden"
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-[248px] shrink-0 flex-col border-r border-border bg-card/70 backdrop-blur-xl",
          "transition-transform duration-[var(--duration-base)] ease-[var(--ease-out-expo)]",
          "md:static md:translate-x-0",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-15 shrink-0 items-center justify-between px-4">
          <Link href="/" className="flex items-center gap-2.5" aria-label="Wizard home">
            <AnimatedOrb size={24} />
            <span className="text-[15px] font-semibold tracking-[-0.02em]">Wizard</span>
          </Link>
          <button
            type="button"
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted md:hidden"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 space-y-0.5 px-2.5 py-2">
          {NAV.map((item) => {
            const Icon = item.icon
            const active = pathname === item.href
            return (
              <Link
                key={item.href}
                href={item.href}
                // Closed here rather than in an effect on `pathname`: navigation
                // is user-initiated, so this is the event, not a consequence to
                // synchronise afterwards.
                onClick={() => setMobileOpen(false)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "group relative flex items-center gap-3 rounded-lg px-3 py-2.5",
                  "transition-colors duration-[var(--duration-fast)]",
                  active ? "bg-card text-foreground shadow-xs" : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
                )}
              >
                {/* The active marker is a bar on the rail edge, not a fill —
                    it survives against the translucent sidebar. */}
                <span
                  className={cn(
                    "absolute -left-2.5 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-brand",
                    "transition-opacity duration-[var(--duration-base)]",
                    active ? "opacity-100" : "opacity-0",
                  )}
                />
                <Icon className="h-4 w-4 shrink-0" />
                <span className="min-w-0 flex-1">
                  <span className="block text-[13.5px] font-medium leading-tight">{item.label}</span>
                  <span className="mt-0.5 block truncate text-[11px] leading-tight text-muted-foreground">
                    {item.hint}
                  </span>
                </span>
              </Link>
            )
          })}
        </nav>

        <div className="shrink-0 border-t border-border px-3 py-3">
          <div className="mb-2 space-y-1.5 px-1">
            <StatusRow
              label="Sandbox"
              value={config ? (config.sandbox_available ? "Container" : "Degraded") : "…"}
              tone={config ? (config.sandbox_available ? "ok" : "warn") : "muted"}
              title={
                config?.sandbox_available
                  ? "Generated code runs in a per-session Docker container."
                  : "Docker is unreachable, so code runs in a restricted in-process interpreter."
              }
            />
            <StatusRow
              label="Queue"
              value={config?.queue_backend ?? "…"}
              tone="muted"
              title="Background job execution backend."
            />
            <StatusRow
              label="Retrieval"
              value={config ? (config.embeddings_semantic ? "Semantic" : "Lexical") : "…"}
              tone="muted"
              title={
                config?.embeddings_semantic
                  ? "A sentence-transformer is loaded."
                  : "No embedding model; scoring falls back to lexical overlap."
              }
            />
          </div>

          <div className="flex items-center justify-between px-1">
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              v{config?.version ?? "—"}
            </span>
            <SoundToggle />
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <button
          type="button"
          onClick={() => setMobileOpen(true)}
          aria-label="Open navigation"
          className="glass absolute left-3 top-3 z-30 flex h-9 w-9 items-center justify-center rounded-lg border border-border text-muted-foreground shadow-sm md:hidden"
        >
          <Menu className="h-4 w-4" />
        </button>

        <main id="main" className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {children}
        </main>
      </div>
    </div>
  )
}

function StatusRow({
  label,
  value,
  tone,
  title,
}: {
  label: string
  value: string
  tone: "ok" | "warn" | "muted"
  title: string
}) {
  return (
    <div className="flex items-center justify-between gap-2" title={title}>
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span
        className={cn(
          "flex items-center gap-1.5 text-[11px] font-medium",
          tone === "ok" && "text-success",
          tone === "warn" && "text-warning",
          tone === "muted" && "text-muted-foreground",
        )}
      >
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            tone === "ok" && "bg-success",
            tone === "warn" && "bg-warning",
            tone === "muted" && "bg-muted-foreground/40",
          )}
        />
        {value}
      </span>
    </div>
  )
}
