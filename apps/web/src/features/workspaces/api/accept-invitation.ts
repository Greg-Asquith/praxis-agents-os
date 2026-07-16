// apps/web/src/features/workspaces/api/accept-invitation.ts

import type {
  WorkspaceInvitationAcceptRequest,
  WorkspaceInvitationAcceptResponse,
} from "@/features/workspaces/types"
import { apiRequest } from "@/lib/api/client"

export async function acceptInvitation(payload: WorkspaceInvitationAcceptRequest) {
  return apiRequest<WorkspaceInvitationAcceptResponse>("/workspaces/invitations/accept", {
    body: payload,
    method: "POST",
  })
}
