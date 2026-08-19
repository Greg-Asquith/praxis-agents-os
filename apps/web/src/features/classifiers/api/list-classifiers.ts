// apps/web/src/features/classifiers/api/list-classifiers.ts

import { queryOptions } from "@tanstack/react-query"

import type { ClassifiersListResponse } from "@/features/classifiers/types"
import { apiRequest } from "@/lib/api/client"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

type ListClassifiersParams = {
  includeInactive?: boolean
  limit?: number
  offset?: number
}

export const classifiersQueryKeys = createWorkspaceScopedQueryKeys("classifiers")

async function listClassifiers({
  includeInactive = true,
  limit = 100,
  offset = 0,
}: ListClassifiersParams = {}) {
  return apiRequest<ClassifiersListResponse>("/classifiers/", {
    query: {
      include_inactive: includeInactive,
      limit,
      offset,
    },
  })
}

export function classifiersQueryOptions(params: ListClassifiersParams = {}) {
  return queryOptions({
    queryKey: classifiersQueryKeys.list(params),
    queryFn: () => listClassifiers(params),
    staleTime: 30_000,
  })
}
