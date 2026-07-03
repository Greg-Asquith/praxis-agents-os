// apps/web/src/features/agents/runtime-tools.ts

import type { ToolCatalogEntry, ToolCatalogPolicy } from "@/features/tools/types"

export type RuntimeToolMode = "off" | ToolCatalogPolicy

export const RUNTIME_TOOL_MODE_LABELS: Record<RuntimeToolMode, string> = {
  approval: "Approval",
  auto: "Auto",
  off: "Off",
}

export function toolModeOptions(entry: ToolCatalogEntry): RuntimeToolMode[] {
  return ["off", ...entry.supported_policies]
}
