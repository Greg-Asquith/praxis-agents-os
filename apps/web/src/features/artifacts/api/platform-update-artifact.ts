// apps/web/src/features/artifacts/api/platform-update-artifact.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { applyPlatformArtifactChange } from "@/features/artifacts/api/platform-list-artifacts"
import type { PlatformArtifact } from "@/features/artifacts/types"
import { apiRequest } from "@/lib/api/client"

type UpdatePlatformArtifactInput = {
  artifactId: string
  content: string
  expectedCurrentVersionId: string
  title?: string
}

async function updatePlatformArtifact({
  artifactId,
  content,
  expectedCurrentVersionId,
  title,
}: UpdatePlatformArtifactInput) {
  return apiRequest<PlatformArtifact>(`/artifacts/platform/${artifactId}`, {
    body: { content, title, expected_current_version_id: expectedCurrentVersionId },
    method: "PATCH",
  })
}

export function useUpdatePlatformArtifactMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: updatePlatformArtifact,
    onSuccess: (artifact) => applyPlatformArtifactChange(queryClient, artifact),
  })
}
