// apps/web/src/features/auth/api/logout.ts

import {
  mutationOptions,
  useMutation,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import { clearActiveWorkspace } from "@/lib/workspace"

async function logout() {
  return apiRequest<{ message: string }>("/auth/logout", {
    method: "POST",
  })
}

export function logoutMutationOptions(queryClient: QueryClient) {
  return mutationOptions({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.clear()
      clearActiveWorkspace()
    },
  })
}

export function useLogoutMutation() {
  const queryClient = useQueryClient()
  return useMutation(logoutMutationOptions(queryClient))
}
