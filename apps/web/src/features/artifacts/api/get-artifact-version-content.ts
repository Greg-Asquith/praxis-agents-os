// apps/web/src/features/artifacts/api/get-artifact-version-content.ts

import { queryOptions } from "@tanstack/react-query"

import { artifactQueryKeys } from "@/features/artifacts/api/list-artifacts"
import type { ArtifactContent } from "@/features/artifacts/types"
import { apiRequest } from "@/lib/api/client"

async function getArtifactVersionContent(artifactId: string, versionId: string) {
  return apiRequest<ArtifactContent>(`/artifacts/${artifactId}/versions/${versionId}/content`)
}

export function artifactVersionContentQueryOptions(artifactId: string, versionId: string) {
  return queryOptions({
    queryKey: artifactQueryKeys.content(artifactId, versionId),
    queryFn: () => getArtifactVersionContent(artifactId, versionId),
    staleTime: Infinity,
  })
}
