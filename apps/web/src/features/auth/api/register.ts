// apps/web/src/features/auth/api/register.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import { currentUserQueryKey, currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import type { AuthResponse, RegisterRequest } from "@/features/auth/types"

async function register(payload: RegisterRequest) {
  return apiRequest<AuthResponse>("/auth/register", {
    body: payload,
    method: "POST",
  })
}

export function useRegisterMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: register,
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
