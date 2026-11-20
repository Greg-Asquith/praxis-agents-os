// apps/web/src/features/memories/components/memory-display.ts

import type { Memory, MemoryAudience, MemoryOrigin, MemoryStatus } from "@/features/memories/types"

export const MEMORY_AUDIENCE_LABELS: Record<MemoryAudience, string> = {
  shared: "Shared",
  private: "Private",
}

// Background learning stays internal; the product calls it "Learned Automatically".
export const MEMORY_ORIGIN_FILTER_LABELS: Record<MemoryOrigin, string> = {
  learned: "Learned Automatically",
  agent: "Saved by Agent",
  person: "Edited by People",
}

export const MEMORY_STATUS_LABELS: Record<MemoryStatus, string> = {
  active: "Active",
  archived: "Archived",
  superseded: "Replaced",
}

export function formatMemoryConfidence(value: number) {
  return `${String(Math.round(value * 100))}%`
}

// Mirrors the API's `source` filter: a person's edit outranks how a memory began.
export function memoryOrigin(memory: Memory): MemoryOrigin {
  if (memory.created_by === "user" || memory.last_edited_by_user_at !== null) {
    return "person"
  }
  return memory.source === "dream" ? "learned" : "agent"
}

export function memoryOriginLabel(
  memory: Memory,
  viewer: { userId: string; isPersonalWorkspace: boolean }
) {
  const origin = memoryOrigin(memory)
  if (origin !== "person") {
    return MEMORY_ORIGIN_FILTER_LABELS[origin]
  }
  // Only its owner can see or edit a private memory.
  const byViewer =
    viewer.isPersonalWorkspace ||
    memory.scope === "user" ||
    (memory.created_by === "user" && memory.created_by_user_id === viewer.userId)
  return byViewer ? "Edited by You" : "Edited by Your Team"
}

// A private or workspace memory reaches every agent; an agent memory only its own.
export function memoryUsedByLabel(memory: Memory) {
  return memory.scope === "agent" ? (memory.agent_name ?? "One Agent") : "All Agents"
}
