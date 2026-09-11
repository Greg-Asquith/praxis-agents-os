// apps/web/src/features/artifacts/api/copy-artifact.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { artifactQueryKeys } from "@/features/artifacts/api/list-artifacts"
import type { Artifact } from "@/features/artifacts/types"
import { apiRequest } from "@/lib/api/client"

type CopyArtifactInput = {
  artifactId: string
  versionId: string
  requestId: string
}

async function copyArtifact({ artifactId, versionId, requestId }: CopyArtifactInput) {
  return apiRequest<Artifact>(`/artifacts/${artifactId}/copy`, {
    body: { version_id: versionId, request_id: requestId },
    method: "POST",
  })
}

export function useCopyArtifactMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: copyArtifact,
    onSuccess: async (copy) => {
      queryClient.setQueryData(artifactQueryKeys.detail(copy.id), copy)
      await queryClient.invalidateQueries({ queryKey: artifactQueryKeys.lists() })
    },
  })
}
