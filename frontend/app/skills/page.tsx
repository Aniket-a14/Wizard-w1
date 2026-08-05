import type { Metadata } from "next"

import { SkillsWorkbench } from "@/components/pages/skills-workbench"

export const metadata: Metadata = {
  title: "Skills",
  description: "Reusable know-how the agent consults, layered by project, account and built-in.",
}

export default function SkillsPage() {
  return <SkillsWorkbench />
}
