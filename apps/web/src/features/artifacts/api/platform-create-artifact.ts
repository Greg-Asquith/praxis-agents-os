// apps/web/src/features/artifacts/api/platform-create-artifact.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { applyPlatformArtifactChange } from "@/features/artifacts/api/platform-list-artifacts"
import type { PlatformArtifact } from "@/features/artifacts/types"
import { apiRequest } from "@/lib/api/client"

type PublishArtifactToPlatformInput = {
  artifactId: string
  versionId: string
  expectedCurrentVersionId: string
  requestId: string
}

async function publishArtifactToPlatform({
  artifactId,
  versionId,
  expectedCurrentVersionId,
  requestId,
}: PublishArtifactToPlatformInput) {
  return apiRequest<PlatformArtifact>(`/artifacts/platform/from-workspace/${artifactId}`, {
    body: {
      version_id: versionId,
      expected_current_version_id: expectedCurrentVersionId,
      request_id: requestId,
    },
    method: "POST",
  })
}

export function usePublishArtifactToPlatformMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: publishArtifactToPlatform,
    onSuccess: (created) => applyPlatformArtifactChange(queryClient, created),
  })
}
