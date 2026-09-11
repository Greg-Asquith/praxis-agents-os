// apps/web/src/features/artifacts/api/platform-get-artifact-version-content.ts

import { queryOptions } from "@tanstack/react-query"

import { platformArtifactQueryKeys } from "@/features/artifacts/api/platform-list-artifacts"
import type { ArtifactContent } from "@/features/artifacts/types"
import { apiRequest } from "@/lib/api/client"

export function platformArtifactVersionContentQueryOptions(artifactId: string, versionId: string) {
  return queryOptions({
    queryKey: platformArtifactQueryKeys.content(artifactId, versionId),
    queryFn: () =>
      apiRequest<ArtifactContent>(`/artifacts/platform/${artifactId}/content`, {
        query: { version_id: versionId },
      }),
    staleTime: Infinity,
  })
}
