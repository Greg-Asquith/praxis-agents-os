// apps/web/src/features/artifacts/api/get-artifact.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { artifactQueryKeys } from "@/features/artifacts/api/list-artifacts"
import type { Artifact } from "@/features/artifacts/types"
import { apiRequest } from "@/lib/api/client"

async function getArtifact(artifactId: string) {
  return apiRequest<Artifact>(`/artifacts/${artifactId}`)
}

export function artifactQueryOptions(artifactId: string) {
  return queryOptions({
    queryKey: artifactQueryKeys.detail(artifactId),
    queryFn: () => getArtifact(artifactId),
    staleTime: 30_000,
  })
}

export function useArtifactQuery(artifactId: string) {
  return useSuspenseQuery(artifactQueryOptions(artifactId))
}
