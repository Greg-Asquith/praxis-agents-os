// apps/web/src/features/artifacts/api/update-artifact.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { artifactQueryKeys } from "@/features/artifacts/api/list-artifacts"
import type { Artifact } from "@/features/artifacts/types"
import { apiRequest } from "@/lib/api/client"

type UpdateArtifactInput = {
  artifactId: string
  content: string
  title?: string
}

async function updateArtifact({ artifactId, content, title }: UpdateArtifactInput) {
  return apiRequest<Artifact>(`/artifacts/${artifactId}`, {
    body: { content, title },
    method: "PATCH",
  })
}

export function useUpdateArtifactMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: updateArtifact,
    onSuccess: async (artifact) => {
      queryClient.setQueryData(artifactQueryKeys.detail(artifact.id), artifact)
      await queryClient.invalidateQueries({ queryKey: artifactQueryKeys.lists() })
    },
  })
}
