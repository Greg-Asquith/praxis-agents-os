// apps/web/src/features/artifacts/api/platform-get-artifact.ts

import { queryOptions } from "@tanstack/react-query"

import { platformArtifactQueryKeys } from "@/features/artifacts/api/platform-list-artifacts"
import type { PlatformArtifact } from "@/features/artifacts/types"
import { apiRequest } from "@/lib/api/client"

export function platformArtifactQueryOptions(artifactId: string) {
  return queryOptions({
    queryKey: platformArtifactQueryKeys.detail(artifactId),
    queryFn: () => apiRequest<PlatformArtifact>(`/artifacts/platform/${artifactId}`),
    staleTime: 0,
  })
}
