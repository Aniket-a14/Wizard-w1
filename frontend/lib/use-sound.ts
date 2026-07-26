"use client"

import { useCallback, useSyncExternalStore } from "react"

/**
 * Interface sound effects.
 *
 * Three things this gets right that a bare `new Audio(url).play()` does not:
 *
 * 1. **One element per sound, reused.** The previous implementation allocated a
 *    fresh `Audio` on every send and every click. Those elements are never
 *    collected while decoding, so a long session accumulated them, and the
 *    first play of each was gated on a fresh network fetch — audible as a lag
 *    between the click and the sound.
 * 2. **A real mute preference**, shared across every component through an
 *    external store and persisted. Sound that cannot be turned off is not
 *    shippable to an office.
 * 3. **Autoplay is expected to fail.** Browsers reject playback until the page
 *    has been interacted with, so the startup sound is armed rather than fired:
 *    it plays on the first genuine gesture if it could not play immediately.
 */

export type SoundName = "click" | "startup"

const SOURCES: Record<SoundName, string> = {
  click: "/sound/click.mp3",
  startup: "/sound/startup.mp3",
}

// Startup is a longer, fuller sample and needs to sit further back than a click.
const VOLUMES: Record<SoundName, number> = {
  click: 0.32,
  startup: 0.45,
}

const STORAGE_KEY = "wizard.sound"

// --------------------------------------------------------------------------
// Preference store
// --------------------------------------------------------------------------
let enabled = true
const listeners = new Set<() => void>()

function readStoredPreference(): boolean {
  if (typeof window === "undefined") return true
  try {
    return window.localStorage.getItem(STORAGE_KEY) !== "off"
  } catch {
    // Private-browsing modes throw on access rather than returning null.
    return true
  }
}

let hydrated = false

function subscribe(listener: () => void): () => void {
  // The first subscriber hydrates from storage. Doing it here rather than in an
  // effect keeps the value correct on the very first render after mount without
  // a synchronous setState, which `react-hooks/set-state-in-effect` forbids.
  if (!hydrated) {
    hydrated = true
    enabled = readStoredPreference()
  }
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function getSnapshot(): boolean {
  return enabled
}

/** The server has no preference to read; assume on so markup matches the common case. */
function getServerSnapshot(): boolean {
  return true
}

function setEnabled(next: boolean): void {
  if (enabled === next) return
  enabled = next
  try {
    window.localStorage.setItem(STORAGE_KEY, next ? "on" : "off")
  } catch {
    // Preference is in-memory only for this session; not worth failing over.
  }
  for (const listener of listeners) listener()
}

// --------------------------------------------------------------------------
// Playback
// --------------------------------------------------------------------------
const pool = new Map<SoundName, HTMLAudioElement>()

/** A sound that could not play because the page had not been interacted with. */
let pendingOnGesture: SoundName | null = null
let gestureListenerAttached = false

function element(name: SoundName): HTMLAudioElement | null {
  if (typeof window === "undefined") return null
  let audio = pool.get(name)
  if (!audio) {
    audio = new Audio(SOURCES[name])
    audio.preload = "auto"
    audio.volume = VOLUMES[name]
    pool.set(name, audio)
  }
  return audio
}

function armGestureFallback(name: SoundName): void {
  pendingOnGesture = name
  if (gestureListenerAttached) return
  gestureListenerAttached = true

  const fire = () => {
    const queued = pendingOnGesture
    pendingOnGesture = null
    gestureListenerAttached = false
    window.removeEventListener("pointerdown", fire)
    window.removeEventListener("keydown", fire)
    if (queued && enabled) void play(queued)
  }

  window.addEventListener("pointerdown", fire, { once: true })
  window.addEventListener("keydown", fire, { once: true })
}

async function play(name: SoundName): Promise<void> {
  if (!enabled) return
  const audio = element(name)
  if (!audio) return
  try {
    // Rewind so rapid repeats retrigger instead of being swallowed while the
    // previous playback is still running.
    audio.currentTime = 0
    await audio.play()
  } catch {
    // NotAllowedError until the document has been interacted with. Queue it.
    if (name === "startup") armGestureFallback(name)
  }
}

/**
 * Warms the decoder so the first real play is instant.
 *
 * Safe to call repeatedly; `load()` on an already-loaded element is a no-op.
 */
export function preloadSounds(): void {
  for (const name of Object.keys(SOURCES) as SoundName[]) {
    element(name)?.load()
  }
}

export interface UseSound {
  /** Whether sound is currently on. */
  soundOn: boolean
  /** Flip the preference and persist it. */
  toggleSound: () => void
  /** Play a sound. Never throws and never rejects. */
  playSound: (name: SoundName) => void
}

export function useSound(): UseSound {
  const soundOn = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)

  const playSound = useCallback((name: SoundName) => {
    void play(name)
  }, [])

  const toggleSound = useCallback(() => {
    const next = !enabled
    setEnabled(next)
    // Confirm the change audibly, but only when turning sound *on* — playing a
    // sound to acknowledge "mute" would be absurd.
    if (next) void play("click")
  }, [])

  return { soundOn, toggleSound, playSound }
}
