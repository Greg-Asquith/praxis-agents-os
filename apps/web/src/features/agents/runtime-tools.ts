// apps/web/src/features/agents/runtime-tools.ts

import type { ToolPolicyValue } from "@/features/agents/types"

// Keep this list aligned with apps/api/services/agents/runtime/tools/registry.py
// until the backend exposes a public runtime-tool catalog endpoint.
export const RUNTIME_TOOL_OPTIONS = [
  {
    name: "get_runtime_context",
    label: "Runtime context",
    description: "Let the agent read workspace and run context during a conversation.",
  },
  {
    name: "add_numbers",
    label: "Add numbers",
    description: "Add two integers and return the result.",
  },
] as const

export type RuntimeToolName = (typeof RUNTIME_TOOL_OPTIONS)[number]["name"]
export type RuntimeToolMode = "off" | ToolPolicyValue

export function runtimeToolLabel(toolName: string) {
  return RUNTIME_TOOL_OPTIONS.find((tool) => tool.name === toolName)?.label ?? null
}

export const RUNTIME_TOOL_MODE_LABELS: Record<RuntimeToolMode, string> = {
  approval: "Approval",
  auto: "Auto",
  off: "Off",
}
