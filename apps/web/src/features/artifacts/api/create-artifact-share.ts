// apps/web/src/features/artifacts/api/create-artifact-share.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { artifactQueryKeys } from "@/features/artifacts/api/list-artifacts"
import type { ArtifactShareCreated } from "@/features/artifacts/types"
import { apiRequest } from "@/lib/api/client"

type CreateArtifactShareInput = {
  artifactId: string
  expiresInDays: number
}

async function createArtifactShare({ artifactId, expiresInDays }: CreateArtifactShareInput) {
  return apiRequest<ArtifactShareCreated>(`/artifacts/${artifactId}/shares`, {
    body: { expires_in_days: expiresInDays },
    method: "POST",
  })
}

export function useCreateArtifactShareMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createArtifactShare,
    onSuccess: async (_created, input) => {
      await queryClient.invalidateQueries({ queryKey: artifactQueryKeys.shares(input.artifactId) })
    },
  })
}
