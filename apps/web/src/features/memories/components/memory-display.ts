// apps/web/src/features/memories/components/memory-display.ts

import type { Memory } from "@/features/memories/types"
import { titleCaseToken } from "@/lib/format"

export function formatMemoryConfidence(value: number) {
  return `${String(Math.round(value * 100))}%`
}

export function memoryScopeLabel(memory: Memory) {
  if (memory.scope === "agent") {
    return memory.agent_name ?? "Agent"
  }
  return memory.scope === "user" ? "Personal" : titleCaseToken(memory.scope, "Scope")
}
