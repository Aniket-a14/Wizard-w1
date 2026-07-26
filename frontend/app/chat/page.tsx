import type { Metadata } from "next"

import { ChatShell } from "@/components/chat-shell"

export const metadata: Metadata = {
  title: "Workspace — Wizard",
  // The old description named DeepSeek-R1 and Qwen2.5-Coder outright, which
  // stopped being true the moment models became a per-session choice.
  description:
    "Ask a question, watch the plan, read the code, keep the result. Running locally on the models you picked.",
}

export default function ChatPage() {
  return <ChatShell />
}
