// apps/web/src/features/artifacts/api/platform-publish-artifact.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { applyPlatformArtifactChange } from "@/features/artifacts/api/platform-list-artifacts"
import type { PlatformArtifact } from "@/features/artifacts/types"
import { apiRequest } from "@/lib/api/client"

type PublishPlatformArtifactInput = {
  artifactId: string
  expectedCurrentVersionId: string
}

async function publishPlatformArtifact({
  artifactId,
  expectedCurrentVersionId,
}: PublishPlatformArtifactInput) {
  return apiRequest<PlatformArtifact>(`/artifacts/platform/${artifactId}/publish`, {
    body: { expected_current_version_id: expectedCurrentVersionId },
    method: "POST",
  })
}

export function usePublishPlatformArtifactMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: publishPlatformArtifact,
    onSuccess: (artifact) => applyPlatformArtifactChange(queryClient, artifact),
  })
}
