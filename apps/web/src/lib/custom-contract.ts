// apps/web/src/lib/custom-contract.ts

import type { LucideIcon } from "lucide-react"

/** One entry on the Tools page. `to` is a custom route under `/tools/`. */
export type CustomTool = {
  to: string
  title: string
  description: string
  icon: LucideIcon
}
