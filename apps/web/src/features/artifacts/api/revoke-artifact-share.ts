// apps/web/src/features/artifacts/api/revoke-artifact-share.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { artifactQueryKeys } from "@/features/artifacts/api/list-artifacts"
import { apiRequestNoContent } from "@/lib/api/client"

type RevokeArtifactShareInput = {
  artifactId: string
  shareId: string
}

async function revokeArtifactShare({ artifactId, shareId }: RevokeArtifactShareInput) {
  return apiRequestNoContent(`/artifacts/${artifactId}/shares/${shareId}`, {
    method: "DELETE",
  })
}

export function useRevokeArtifactShareMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: revokeArtifactShare,
    onSuccess: async (_result, input) => {
      await queryClient.invalidateQueries({ queryKey: artifactQueryKeys.shares(input.artifactId) })
    },
  })
}
