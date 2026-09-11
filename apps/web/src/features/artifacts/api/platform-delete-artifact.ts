// apps/web/src/features/artifacts/api/platform-delete-artifact.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { artifactQueryKeys } from "@/features/artifacts/api/list-artifacts"
import {
  applyPlatformArtifactChange,
  platformArtifactQueryKeys,
} from "@/features/artifacts/api/platform-list-artifacts"
import { apiRequestNoContent } from "@/lib/api/client"

async function deletePlatformArtifact(artifactId: string) {
  return apiRequestNoContent(`/artifacts/platform/${artifactId}`, { method: "DELETE" })
}

export function useDeletePlatformArtifactMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deletePlatformArtifact,
    onSuccess: async (_result, artifactId) => {
      queryClient.removeQueries({ queryKey: platformArtifactQueryKeys.detail(artifactId) })
      queryClient.removeQueries({ queryKey: artifactQueryKeys.detail(artifactId) })
      await applyPlatformArtifactChange(queryClient)
    },
  })
}
