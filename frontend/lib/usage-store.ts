"use client"

import { useSyncExternalStore } from "react"

import type { UsageTotals } from "./types"

/**
 * The session's running cost, shared between the chat socket and the rail.
 *
 * The socket learns what a turn cost the moment it ends — the backend sends a
 * `usage` frame carrying the session totals — while the readout that displays it
 * lives in the nav rail, on the other side of the tree. A store is how they meet
 * without the rail polling or the chat shell owning something it does not render.
 *
 * `useSyncExternalStore` rather than an effect, for the same reason `use-sound`
 * uses it: `react-hooks/set-state-in-effect` is an error in this project, and
 * subscribing is not a state update.
 */

let current: UsageTotals | null = null
const listeners = new Set<() => void>()

function emit() {
  for (const listener of listeners) listener()
}

/** Replaces the totals and notifies every reader. */
export function setUsage(totals: UsageTotals | null) {
  current = totals
  emit()
}

/**
 * Records what a turn cost from a `usage` frame.
 *
 * The frame carries session totals, not a delta, so this is a replace rather
 * than an accumulate — the backend's ledger is the single source of truth and
 * adding on the client would double-count a reconnect.
 */
export function recordUsageFrame(frame: Record<string, unknown>) {
  const totals: UsageTotals = {
    records: Array.isArray(frame.records) ? (frame.records as UsageTotals["records"]) : [],
    calls: Number(frame.calls ?? 0),
    input_tokens: Number(frame.input_tokens ?? 0),
    output_tokens: Number(frame.output_tokens ?? 0),
    total_tokens: Number(frame.total_tokens ?? 0),
    cost_usd: typeof frame.cost_usd === "number" ? frame.cost_usd : null,
    any_cloud: Boolean(frame.any_cloud),
    estimated: Boolean(frame.estimated),
    unpriced_models: Array.isArray(frame.unpriced_models) ? (frame.unpriced_models as string[]) : [],
    // The frame is only sent when a cloud model ran, so by construction this
    // session is not local-only.
    local_only: false,
  }
  setUsage(totals)
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function getSnapshot(): UsageTotals | null {
  return current
}

/** Server render has no session, so there is nothing to report yet. */
function getServerSnapshot(): UsageTotals | null {
  return null
}

export function useUsage(): UsageTotals | null {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}
