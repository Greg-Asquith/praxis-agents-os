// apps/web/src/features/memories/components/memory-filters.ts

import type { MemoryKind, MemoryScope, MemoryStatus, MemoryType } from "@/features/memories/types"

export type MemoryFilters = {
  scope: MemoryScope | ""
  kind: MemoryKind | ""
  memoryType: MemoryType | ""
  agentId: string
  status: MemoryStatus
}

export const DEFAULT_MEMORY_FILTERS: MemoryFilters = {
  scope: "",
  kind: "",
  memoryType: "",
  agentId: "",
  status: "active",
}
