"use client"

import { useEffect, useRef } from "react"

import { cn } from "@/lib/utils"

/**
 * Reveals its children once they scroll into view.
 *
 * The visible flag is written straight to the DOM as a data attribute instead of
 * being held in React state. Scroll-driven state changes would re-render a whole
 * section on every intersection, and the styling is pure CSS anyway — React
 * never needs to know. It also sidesteps `react-hooks/set-state-in-effect`,
 * which this config treats as an error.
 */
export function Reveal({
  children,
  className,
  delay = 0,
  as: Tag = "div",
}: {
  children: React.ReactNode
  className?: string
  /** Milliseconds to hold before this element animates. Use to cascade siblings. */
  delay?: number
  as?: "div" | "section" | "li" | "header" | "footer"
}) {
  const ref = useRef<HTMLElement>(null)

  useEffect(() => {
    const node = ref.current
    if (!node) return

    // Elements already on screen at mount should not wait for a scroll event.
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.setAttribute("data-visible", "true")
            observer.unobserve(entry.target)
          }
        }
      },
      // Fire a little before the element is fully in view: by the time the
      // reader's eye arrives the animation has already begun, which reads as
      // responsive rather than as content popping in late.
      { rootMargin: "0px 0px -12% 0px", threshold: 0.08 },
    )

    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  return (
    <Tag
      ref={ref as never}
      data-reveal=""
      style={{ transitionDelay: `${delay}ms` }}
      className={cn(
        "translate-y-6 opacity-0 blur-[8px]",
        "transition-[opacity,transform,filter] duration-[900ms] ease-[var(--ease-out-expo)]",
        "data-[visible=true]:translate-y-0 data-[visible=true]:opacity-100 data-[visible=true]:blur-0",
        "motion-reduce:translate-y-0 motion-reduce:opacity-100 motion-reduce:blur-0",
        className,
      )}
    >
      {children}
    </Tag>
  )
}
