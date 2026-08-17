// apps/web/src/features/workspaces/routes/accept-invitation-loader.ts

import type { QueryClient } from "@tanstack/react-query"

import { acceptInvitation } from "@/features/workspaces/api/accept-invitation"
import { workspacesQueryKey } from "@/features/workspaces/api/list-workspaces"
import type { WorkspaceInvitationAcceptResponse } from "@/features/workspaces/types"
import { ApiError, getErrorMessage } from "@/lib/api/errors"

const acceptInvitationPromises = new Map<string, Promise<WorkspaceInvitationAcceptResponse>>()

export async function loadAcceptInvitation({
  queryClient,
  token: rawToken,
}: {
  queryClient: QueryClient
  token: string | undefined
}) {
  const token = rawToken?.trim() ?? ""
  if (!token) {
    return { error: "This invitation link is missing a token.", errorReason: null, result: null }
  }

  let result: WorkspaceInvitationAcceptResponse
  try {
    result = await acceptInvitationOnce(token)
  } catch (error) {
    const errorReason =
      error instanceof ApiError && error.problem?.["reason"] === "invitation_email_mismatch"
        ? "invitation_email_mismatch"
        : null
    return { error: getErrorMessage(error), errorReason, result: null }
  }

  await queryClient.invalidateQueries({ queryKey: workspacesQueryKey })
  return { error: null, errorReason: null, result }
}

function acceptInvitationOnce(token: string) {
  const existing = acceptInvitationPromises.get(token)
  if (existing) {
    return existing
  }

  const promise = acceptInvitation({ token })
  acceptInvitationPromises.set(token, promise)
  return promise
}
