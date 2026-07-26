import type { Metadata } from "next"

import { SettingsWorkbench } from "@/components/pages/settings-workbench"

export const metadata: Metadata = {
  title: "Settings",
  description: "Session controls, interface preferences and server diagnostics.",
}

export default function SettingsPage() {
  return <SettingsWorkbench />
}
