// apps/web/src/features/artifacts/api/create-view-url.ts

import type { ArtifactViewGrant } from "@/features/artifacts/types"
import { apiRequest } from "@/lib/api/client"

export function createArtifactViewUrl(artifactId: string, versionId: string) {
  return apiRequest<ArtifactViewGrant>(`/artifacts/${artifactId}/versions/${versionId}/view-url`)
}
