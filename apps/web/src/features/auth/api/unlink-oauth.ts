// apps/web/src/features/auth/api/unlink-oauth.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import { identitiesQueryKey } from "@/features/auth/api/get-identities"
import type { IdentitiesResponse } from "@/features/auth/types"

async function unlinkOauth(provider: string) {
  return apiRequest<IdentitiesResponse>(`/auth/oauth/${provider}/link`, {
    method: "DELETE",
  })
}

export function useUnlinkOauthMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: unlinkOauth,
    onSuccess: (identities) => {
      queryClient.setQueryData(identitiesQueryKey, identities)
    },
  })
}
