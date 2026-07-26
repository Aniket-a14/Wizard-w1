"use client"

import type React from "react"

import { cn } from "@/lib/utils"

/**
 * The product's mark: five blurred circles orbiting a tinted disc.
 *
 * Recovered from the pre-rewrite frontend. Two values are computed from `size`
 * rather than fixed, because this renders at 18px in the footer and 128px in
 * the hero and the original constants only looked right at one of those:
 *
 * - **Blur** scales with the orb, or a small instance turns into mush.
 * - **The drop shadow** scales too. It was pinned at `0 48px 100px`, which is a
 *   hero-sized glow; under a 26px nav mark it read as a smudge on the header.
 *
 * The orbit, counter-rotation and hue cycling all live in `globals.css`, which
 * is also where `prefers-reduced-motion` stops them.
 */
export function AnimatedOrb({
  className,
  variant = "default",
  size = 32,
}: {
  className?: string
  variant?: "default" | "red"
  size?: number
}) {
  const colors =
    variant === "red"
      ? {
          bg: "#fef2f2",
          circle1: "#ef4444",
          circle2: "#f87171",
          circle3: "#dc2626",
          circle4: "#fca5a5",
          circle5: "#fb7185",
        }
      : {
          bg: "#cff1f4",
          circle1: "#9e9fef",
          circle2: "#c471ec",
          circle3: "#9bc761",
          circle4: "#ccd4f2",
          circle5: "#f472b6",
        }

  const blurAmount = Math.max(4, size * 0.15)

  // Circles are sized as fractions of the orb so the composition holds at any scale.
  const circles = [
    { key: "orb-circle-1", scale: 0.45, opacity: 0.9, color: colors.circle1 },
    { key: "orb-circle-2", scale: 0.35, opacity: 0.85, color: colors.circle2 },
    { key: "orb-circle-3", scale: 0.5, opacity: 0.9, color: colors.circle3 },
    { key: "orb-circle-4", scale: 0.25, opacity: 0.8, color: colors.circle4 },
    { key: "orb-circle-5", scale: 0.3, opacity: 0.85, color: colors.circle5 },
  ]

  return (
    <div
      className={cn("relative shrink-0 overflow-hidden rounded-full", className)}
      style={{
        width: size,
        height: size,
        backgroundColor: colors.bg,
        animation: "orb-hue-rotate 8s linear infinite",
        boxShadow: `rgba(17, 12, 46, 0.16) 0px ${size * 0.36}px ${size * 0.78}px 0px`,
      }}
      aria-hidden="true"
    >
      <div
        className="absolute inset-0 flex items-center justify-center"
        style={
          {
            "--orb-blur": `${blurAmount}px`,
            animation: "orb-hue-rotate-blur 6s linear infinite reverse",
          } as React.CSSProperties
        }
      >
        {circles.map((circle) => (
          <div
            key={circle.key}
            className={cn(circle.key, "absolute rounded-full")}
            style={{
              width: size * circle.scale,
              height: size * circle.scale,
              opacity: circle.opacity,
              backgroundColor: circle.color,
            }}
          />
        ))}
      </div>

      {/* Specular highlight: sells it as a sphere rather than a flat disc. */}
      <div
        className="pointer-events-none absolute inset-0 rounded-full"
        style={{
          background: "linear-gradient(to bottom, rgba(255, 255, 255, 0.4) 0%, transparent 100%)",
        }}
      />
    </div>
  )
}
