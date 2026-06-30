// apps/web/src/features/workspaces/api/update-workspace.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import { workspacesQueryKey } from "@/features/workspaces/api/list-workspaces"
import type { Workspace, WorkspaceUpdateRequest } from "@/features/workspaces/types"

type UpdateWorkspaceInput = {
  workspaceId: string
  payload: WorkspaceUpdateRequest
}

async function updateWorkspace({ workspaceId, payload }: UpdateWorkspaceInput) {
  return apiRequest<Workspace>(`/workspaces/${workspaceId}`, {
    body: payload,
    method: "PATCH",
  })
}

export function useUpdateWorkspaceMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: updateWorkspace,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: workspacesQueryKey })
    },
  })
}
