"use client"

import { useEffect, useState, useRef } from "react"

interface AnalysisWordSpanProps {
  word: string
}

export function AnalysisWordSpan({ word }: AnalysisWordSpanProps) {
  const [blurAmount, setBlurAmount] = useState(16)
  const [opacity, setOpacity] = useState(0)
  const [animationComplete, setAnimationComplete] = useState(false)
  const animationRef = useRef<number | null>(null)
  const mountedRef = useRef(false)

  useEffect(() => {
    if (mountedRef.current) return
    mountedRef.current = true

    const startTime = performance.now()
    const duration = 600

    const animateBlur = (currentTime: number) => {
      const elapsed = currentTime - startTime
      const progress = Math.min(elapsed / duration, 1)

      const easeOut = 1 - Math.pow(1 - progress, 3)
      const newBlur = 16 * (1 - easeOut)
      const newOpacity = easeOut

      setBlurAmount(newBlur)
      setOpacity(newOpacity)

      if (progress < 1) {
        animationRef.current = requestAnimationFrame(animateBlur)
      } else {
        setAnimationComplete(true)
      }
    }

    animationRef.current = requestAnimationFrame(animateBlur)

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
    }
  }, [])

  return (
    <span
      className="inline text-stone-900"
      style={{
        filter: animationComplete ? "none" : `blur(${blurAmount}px)`,
        opacity: animationComplete ? 1 : opacity,
      }}
    >
      {word}
    </span>
  )
}
