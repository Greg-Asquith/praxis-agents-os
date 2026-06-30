// apps/web/src/features/auth/api/update-current-user.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import { currentUserQueryKey } from "@/features/auth/api/get-current-user"
import type { AuthUser, UpdateCurrentUserRequest } from "@/features/auth/types"

async function updateCurrentUser(payload: UpdateCurrentUserRequest) {
  return apiRequest<AuthUser>("/auth/me", {
    body: payload,
    method: "PATCH",
  })
}

export function useUpdateCurrentUserMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: updateCurrentUser,
    onSuccess: (user) => {
      queryClient.setQueryData(currentUserQueryKey, user)
    },
  })
}
