// apps/web/src/features/artifacts/api/platform-restore-artifact-version.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { applyPlatformArtifactChange } from "@/features/artifacts/api/platform-list-artifacts"
import type { PlatformArtifact } from "@/features/artifacts/types"
import { apiRequest } from "@/lib/api/client"

type RestorePlatformArtifactVersionInput = {
  artifactId: string
  versionId: string
  expectedCurrentVersionId: string
}

async function restorePlatformArtifactVersion({
  artifactId,
  versionId,
  expectedCurrentVersionId,
}: RestorePlatformArtifactVersionInput) {
  return apiRequest<PlatformArtifact>(`/artifacts/platform/${artifactId}/restore`, {
    body: { version_id: versionId, expected_current_version_id: expectedCurrentVersionId },
    method: "POST",
  })
}

export function useRestorePlatformArtifactVersionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: restorePlatformArtifactVersion,
    onSuccess: (artifact) => applyPlatformArtifactChange(queryClient, artifact),
  })
}
