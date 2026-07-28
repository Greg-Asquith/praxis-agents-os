// apps/web/src/features/artifacts/api/restore-artifact-version.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { artifactQueryKeys } from "@/features/artifacts/api/list-artifacts"
import type { Artifact } from "@/features/artifacts/types"
import { apiRequest } from "@/lib/api/client"

type RestoreArtifactVersionInput = {
  artifactId: string
  versionId: string
}

async function restoreArtifactVersion({ artifactId, versionId }: RestoreArtifactVersionInput) {
  return apiRequest<Artifact>(`/artifacts/${artifactId}/versions/${versionId}/restore`, {
    method: "POST",
  })
}

export function useRestoreArtifactVersionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: restoreArtifactVersion,
    onSuccess: async (artifact) => {
      queryClient.setQueryData(artifactQueryKeys.detail(artifact.id), artifact)
      await queryClient.invalidateQueries({ queryKey: artifactQueryKeys.lists() })
    },
  })
}
