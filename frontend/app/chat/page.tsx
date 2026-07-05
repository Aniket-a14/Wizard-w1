import { ChatShell } from "@/components/chat-shell"
import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Chat - Wizard w1",
  description: "Advanced AI Data Analyst Platform powered by DeepSeek-R1 and Qwen2.5-Coder",
}

export default function ChatPage() {
  return <ChatShell />
}
