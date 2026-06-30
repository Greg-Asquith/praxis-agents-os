// apps/web/src/features/auth/api/logout.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { workspacesQueryOptions } from "@/features/workspaces/api/list-workspaces"

async function logout() {
  return apiRequest<{ message: string }>("/auth/logout", {
    method: "POST",
  })
}

export function useLogoutMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: currentUserQueryOptions().queryKey })
      queryClient.removeQueries({ queryKey: workspacesQueryOptions().queryKey })
    },
  })
}
