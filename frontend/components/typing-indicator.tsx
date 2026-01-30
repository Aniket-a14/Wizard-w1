"use client"

import { AnimatedOrb } from "./animated-orb"

export function TypingIndicator() {
  return (
    <div className="flex gap-3 max-w-[90%] md:max-w-[80%] mr-auto animate-in fade-in slide-in-from-bottom-2 duration-300">
      <div className="shrink-0">
        <AnimatedOrb size={32} />
      </div>

      {/* Typing dots */}
      <div
        className="px-4 py-3 rounded-2xl rounded-bl-md bg-white border border-stone-200"
        style={{
          boxShadow:
            "rgba(14, 63, 126, 0.04) 0px 0px 0px 1px, rgba(42, 51, 69, 0.04) 0px 1px 1px -0.5px, rgba(42, 51, 70, 0.04) 0px 3px 3px -1.5px, rgba(42, 51, 70, 0.04) 0px 6px 6px -3px, rgba(14, 63, 126, 0.04) 0px 12px 12px -6px, rgba(14, 63, 126, 0.04) 0px 24px 24px -12px",
        }}
        role="status"
        aria-label="Assistant is typing"
      >
        <div className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-stone-400 animate-bounce" style={{ animationDelay: "0ms" }} />
          <span className="w-2 h-2 rounded-full bg-stone-400 animate-bounce" style={{ animationDelay: "150ms" }} />
          <span className="w-2 h-2 rounded-full bg-stone-400 animate-bounce" style={{ animationDelay: "300ms" }} />
        </div>
      </div>
    </div>
  )
}
