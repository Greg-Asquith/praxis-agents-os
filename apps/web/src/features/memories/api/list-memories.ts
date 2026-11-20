// apps/web/src/features/memories/api/list-memories.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import type {
  MemoriesListResponse,
  MemoryAudience,
  MemoryOrigin,
  MemoryStatus,
  MemoryType,
} from "@/features/memories/types"
import { apiRequest } from "@/lib/api/client"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

export type ListMemoriesParams = {
  audience?: MemoryAudience
  memoryType?: MemoryType
  agentId?: string
  status?: MemoryStatus
  q?: string
  source?: MemoryOrigin
  limit?: number
  offset?: number
}

export const memoriesQueryKeys = createWorkspaceScopedQueryKeys("memories")

async function listMemories(params: ListMemoriesParams = {}) {
  return apiRequest<MemoriesListResponse>("/memories/", {
    query: {
      audience: params.audience,
      memory_type: params.memoryType,
      agent_id: params.agentId,
      status: params.status ?? "active",
      q: params.q,
      source: params.source,
      limit: params.limit ?? 50,
      offset: params.offset ?? 0,
    },
  })
}

export function memoriesQueryOptions(params: ListMemoriesParams = {}) {
  return queryOptions({
    queryKey: memoriesQueryKeys.list(params),
    queryFn: () => listMemories(params),
    staleTime: 30_000,
  })
}

export function useMemoriesQuery(params: ListMemoriesParams = {}) {
  return useSuspenseQuery(memoriesQueryOptions(params))
}
