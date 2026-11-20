// apps/web/src/features/memories/components/memory-filters.ts

import type { ListMemoriesParams } from "@/features/memories/api/list-memories"
import type {
  MemoryAudience,
  MemoryOrigin,
  MemoryStatus,
  MemoryType,
} from "@/features/memories/types"

export const MEMORY_PAGE_SIZE = 50

export type MemoryFilters = {
  audience: MemoryAudience
  q: string
  source: MemoryOrigin | ""
  agentId: string
  memoryType: MemoryType | ""
  status: MemoryStatus
}

export const DEFAULT_MEMORY_FILTERS: MemoryFilters = {
  audience: "shared",
  q: "",
  source: "",
  agentId: "",
  memoryType: "",
  status: "active",
}

export function memoryListParams(filters: MemoryFilters, offset: number): ListMemoriesParams {
  return {
    audience: filters.audience,
    status: filters.status,
    ...(filters.q ? { q: filters.q } : {}),
    ...(filters.source ? { source: filters.source } : {}),
    ...(filters.audience === "shared" && filters.agentId ? { agentId: filters.agentId } : {}),
    ...(filters.memoryType ? { memoryType: filters.memoryType } : {}),
    limit: MEMORY_PAGE_SIZE,
    offset,
  }
}

// True when anything beyond the tab narrows the list.
export function hasNarrowingFilters(filters: MemoryFilters) {
  return Boolean(
    filters.q ||
    filters.source ||
    filters.agentId ||
    filters.memoryType ||
    filters.status !== DEFAULT_MEMORY_FILTERS.status
  )
}
