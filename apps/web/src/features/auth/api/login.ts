// apps/web/src/features/auth/api/login.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import { currentUserQueryKey, currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import type { AuthResponse, LoginRequest } from "@/features/auth/types"

async function login(payload: LoginRequest) {
  return apiRequest<AuthResponse>("/auth/login", {
    body: payload,
    method: "POST",
  })
}

export function useLoginMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: login,
    onSuccess: async (response) => {
      if (response.user) {
        queryClient.setQueryData(currentUserQueryKey, response.user)
      }
      await queryClient.invalidateQueries({
        queryKey: currentUserQueryOptions().queryKey,
      })
    },
  })
}
