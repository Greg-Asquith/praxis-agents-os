// apps/web/src/features/memories/api/get-memory.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { memoriesQueryKeys } from "@/features/memories/api/list-memories"
import type { MemoryDetailResponse } from "@/features/memories/types"
import { apiRequest } from "@/lib/api/client"

function memoryDetailQueryOptions(memoryId: string) {
  return queryOptions({
    queryKey: memoriesQueryKeys.detail(memoryId),
    queryFn: () => apiRequest<MemoryDetailResponse>(`/memories/${memoryId}`),
    staleTime: 30_000,
  })
}

export function useMemoryDetailQuery(memoryId: string) {
  return useSuspenseQuery(memoryDetailQueryOptions(memoryId))
}
