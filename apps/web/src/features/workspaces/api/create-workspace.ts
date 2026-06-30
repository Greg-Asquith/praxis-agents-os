// apps/web/src/features/workspaces/api/create-workspace.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import { workspacesQueryKey } from "@/features/workspaces/api/list-workspaces"
import type { Workspace, WorkspaceCreateRequest } from "@/features/workspaces/types"

async function createWorkspace(payload: WorkspaceCreateRequest) {
  return apiRequest<Workspace>("/workspaces/", {
    body: payload,
    method: "POST",
  })
}

export function useCreateWorkspaceMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: createWorkspace,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: workspacesQueryKey })
    },
  })
}
