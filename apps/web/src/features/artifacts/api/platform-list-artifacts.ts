// apps/web/src/features/artifacts/api/platform-list-artifacts.ts

import { queryOptions, type QueryClient } from "@tanstack/react-query"

import { artifactQueryKeys } from "@/features/artifacts/api/list-artifacts"
import type { PlatformArtifact, PlatformArtifactListResponse } from "@/features/artifacts/types"
import { apiRequest } from "@/lib/api/client"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

const basePlatformArtifactQueryKeys = createWorkspaceScopedQueryKeys("platform-artifacts")

export const platformArtifactQueryKeys = {
  ...basePlatformArtifactQueryKeys,
  content: (artifactId: string, versionId: string) =>
    [...platformArtifactQueryKeys.detail(artifactId), "content", versionId] as const,
}

export function platformArtifactsQueryOptions({
  limit = 25,
  offset = 0,
}: { limit?: number; offset?: number } = {}) {
  return queryOptions({
    queryKey: platformArtifactQueryKeys.list({ limit, offset }),
    queryFn: () =>
      apiRequest<PlatformArtifactListResponse>("/artifacts/platform/", {
        query: { limit, offset },
      }),
    staleTime: 0,
  })
}

// Platform changes alter what every workspace reads, so both caches reset across workspace keys.
export async function applyPlatformArtifactChange(
  queryClient: QueryClient,
  artifact?: PlatformArtifact
) {
  if (artifact) {
    queryClient.setQueryData(platformArtifactQueryKeys.detail(artifact.id), artifact)
    queryClient.setQueryData(artifactQueryKeys.detail(artifact.id), artifact)
  }
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: platformArtifactQueryKeys.all }),
    queryClient.invalidateQueries({ queryKey: artifactQueryKeys.all }),
  ])
}
