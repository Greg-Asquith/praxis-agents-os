// apps/web/src/features/artifacts/api/list-artifact-shares.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { artifactQueryKeys } from "@/features/artifacts/api/list-artifacts"
import type { ArtifactShareListResponse } from "@/features/artifacts/types"
import { apiRequest } from "@/lib/api/client"

async function listArtifactShares(artifactId: string) {
  return apiRequest<ArtifactShareListResponse>(`/artifacts/${artifactId}/shares`)
}

function artifactSharesQueryOptions(artifactId: string) {
  return queryOptions({
    queryKey: artifactQueryKeys.shares(artifactId),
    queryFn: () => listArtifactShares(artifactId),
    staleTime: 15_000,
  })
}

export function useArtifactSharesQuery(artifactId: string) {
  return useSuspenseQuery(artifactSharesQueryOptions(artifactId))
}
