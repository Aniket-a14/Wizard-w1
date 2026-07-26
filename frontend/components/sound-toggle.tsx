"use client"

import { Volume2, VolumeX } from "lucide-react"

import { useSound } from "@/lib/use-sound"
import { cn } from "@/lib/utils"

/**
 * Mute control.
 *
 * Deliberately always visible rather than buried in a settings menu: an
 * interface that makes noise has to make silencing it the obvious next click.
 */
export function SoundToggle({ className }: { className?: string }) {
  const { soundOn, toggleSound } = useSound()

  return (
    <button
      type="button"
      onClick={toggleSound}
      aria-label={soundOn ? "Mute interface sounds" : "Unmute interface sounds"}
      aria-pressed={soundOn}
      title={soundOn ? "Sound on" : "Sound off"}
      className={cn(
        "flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground",
        "transition-colors duration-[var(--duration-fast)] hover:bg-muted hover:text-foreground",
        className,
      )}
    >
      {soundOn ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
    </button>
  )
}
