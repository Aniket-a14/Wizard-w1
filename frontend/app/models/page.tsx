import type { Metadata } from "next"

import { ModelsWorkbench } from "@/components/pages/models-workbench"

export const metadata: Metadata = {
  title: "Models",
  description: "Choose which model fills each role, and which backend it runs on.",
}

export default function ModelsPage() {
  return <ModelsWorkbench />
}
