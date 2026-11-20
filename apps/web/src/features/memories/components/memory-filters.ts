// apps/web/src/features/memories/components/memory-filters.ts

import type { MemoryScope, MemoryStatus, MemoryType } from "@/features/memories/types"

export type MemoryFilters = {
  scope: MemoryScope | ""
  memoryType: MemoryType | ""
  agentId: string
  status: MemoryStatus
}

export const DEFAULT_MEMORY_FILTERS: MemoryFilters = {
  scope: "",
  memoryType: "",
  agentId: "",
  status: "active",
}
