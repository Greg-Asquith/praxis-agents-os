// apps/web/src/features/workspaces/api/create-invitation.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import { workspaceInvitationsQueryKey } from "@/features/workspaces/api/list-invitations"
import type {
  WorkspaceInvitationCreateRequest,
  WorkspaceInvitationCreateResponse,
} from "@/features/workspaces/types"

type CreateInvitationInput = {
  workspaceId: string
  payload: WorkspaceInvitationCreateRequest
}

async function createInvitation({ workspaceId, payload }: CreateInvitationInput) {
  return apiRequest<WorkspaceInvitationCreateResponse>(`/workspaces/${workspaceId}/invitations`, {
    body: payload,
    method: "POST",
  })
}

export function useCreateInvitationMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: createInvitation,
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({
        queryKey: workspaceInvitationsQueryKey(variables.workspaceId),
      })
    },
  })
}
