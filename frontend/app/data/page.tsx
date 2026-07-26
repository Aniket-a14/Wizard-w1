import type { Metadata } from "next"

import { DataWorkbench } from "@/components/pages/data-workbench"

export const metadata: Metadata = {
  title: "Data",
  description: "Load, inspect and switch between the datasets in this session.",
}

export default function DataPage() {
  return <DataWorkbench />
}
