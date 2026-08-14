// apps/web/src/features/artifacts/api/list-artifacts.ts

import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query"

import type {
  ArtifactListResponse,
  ArtifactSortDirection,
  ArtifactSortField,
} from "@/features/artifacts/types"
import { apiRequest } from "@/lib/api/client"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

const baseArtifactQueryKeys = createWorkspaceScopedQueryKeys("artifacts")

export const artifactQueryKeys = {
  ...baseArtifactQueryKeys,
  content: (artifactId: string, versionId: string) =>
    [...artifactQueryKeys.detail(artifactId), "content", versionId] as const,
  shares: (artifactId: string) => [...artifactQueryKeys.detail(artifactId), "shares"] as const,
}

export type ListArtifactsParams = {
  limit?: number
  offset?: number
  search?: string
  sortBy?: ArtifactSortField
  sortDirection?: ArtifactSortDirection
}

async function listArtifacts({
  limit = 50,
  offset = 0,
  search,
  sortBy = "updated_at",
  sortDirection = "desc",
}: ListArtifactsParams = {}) {
  return apiRequest<ArtifactListResponse>("/artifacts/", {
    query: {
      limit,
      offset,
      search,
      sort_by: sortBy,
      sort_direction: sortDirection,
    },
  })
}

export function artifactsQueryOptions(params: ListArtifactsParams = {}) {
  return queryOptions({
    queryKey: artifactQueryKeys.list(params),
    queryFn: () => listArtifacts(params),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
}

export function useArtifactsQuery(params: ListArtifactsParams = {}) {
  return useQuery(artifactsQueryOptions(params))
}
