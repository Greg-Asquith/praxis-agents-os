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

// Background learning stays internal; the product calls it "Learned Automatically".
export function memoryOriginLabel(memory: Memory) {
  if (memory.source === "dream") {
    return "Learned Automatically"
  }
  return `${titleCaseToken(memory.created_by, "Unknown")} · ${titleCaseToken(memory.source, "Unknown")}`
}
