// apps/web/src/features/workspaces/api/delete-workspace.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import { workspacesQueryKey } from "@/features/workspaces/api/list-workspaces"

async function deleteWorkspace(workspaceId: string) {
  return apiRequest<undefined>(`/workspaces/${workspaceId}`, {
    method: "DELETE",
  })
}

export function useDeleteWorkspaceMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: deleteWorkspace,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: workspacesQueryKey })
    },
  })
}
