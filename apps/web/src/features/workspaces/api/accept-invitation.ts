// apps/web/src/features/workspaces/api/accept-invitation.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { workspacesQueryKey } from "@/features/workspaces/api/list-workspaces"
import type {
  WorkspaceInvitationAcceptRequest,
  WorkspaceInvitationAcceptResponse,
} from "@/features/workspaces/types"
import { apiRequest } from "@/lib/api/client"

async function acceptInvitation(payload: WorkspaceInvitationAcceptRequest) {
  return apiRequest<WorkspaceInvitationAcceptResponse>("/workspaces/invitations/accept", {
    body: payload,
    method: "POST",
  })
}

export function useAcceptInvitationMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: acceptInvitation,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: workspacesQueryKey })
    },
  })
}
