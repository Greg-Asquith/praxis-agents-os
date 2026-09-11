// apps/web/src/features/artifacts/api/platform-withdraw-artifact.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { applyPlatformArtifactChange } from "@/features/artifacts/api/platform-list-artifacts"
import type { PlatformArtifact } from "@/features/artifacts/types"
import { apiRequest } from "@/lib/api/client"

async function withdrawPlatformArtifact(artifactId: string) {
  return apiRequest<PlatformArtifact>(`/artifacts/platform/${artifactId}/withdraw`, {
    method: "POST",
  })
}

export function useWithdrawPlatformArtifactMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: withdrawPlatformArtifact,
    onSuccess: (artifact) => applyPlatformArtifactChange(queryClient, artifact),
  })
}
