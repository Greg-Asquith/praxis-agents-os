// apps/web/src/features/artifacts/api/list-artifacts.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import type { ArtifactListResponse } from "@/features/artifacts/types"
import { apiRequest } from "@/lib/api/client"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

const baseArtifactQueryKeys = createWorkspaceScopedQueryKeys("artifacts")

export const artifactQueryKeys = {
  ...baseArtifactQueryKeys,
  content: (artifactId: string, versionId: string) =>
    [...artifactQueryKeys.detail(artifactId), "content", versionId] as const,
  shares: (artifactId: string) => [...artifactQueryKeys.detail(artifactId), "shares"] as const,
}

async function listArtifacts() {
  return apiRequest<ArtifactListResponse>("/artifacts/", {
    query: { limit: 100, offset: 0 },
  })
}

export function artifactsQueryOptions() {
  return queryOptions({
    queryKey: artifactQueryKeys.list({ limit: 100, offset: 0 }),
    queryFn: listArtifacts,
    staleTime: 30_000,
  })
}

export function useArtifactsQuery() {
  return useSuspenseQuery(artifactsQueryOptions())
}
