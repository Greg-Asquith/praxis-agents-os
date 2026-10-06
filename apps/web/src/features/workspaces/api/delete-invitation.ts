// apps/web/src/features/workspaces/api/delete-invitation.ts

import {
  mutationOptions,
  useMutation,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query"

import { workspaceInvitationsQueryKey } from "@/features/workspaces/api/list-invitations"
import { apiRequestNoContent } from "@/lib/api/client"

export function deleteInvitationMutationOptions(queryClient: QueryClient) {
  return mutationOptions({
    mutationFn: ({ workspaceId, invitationId }: { workspaceId: string; invitationId: string }) =>
      apiRequestNoContent(`/workspaces/${workspaceId}/invitations/${invitationId}`, {
        method: "DELETE",
      }),
    onSuccess: async (_data, { workspaceId }) => {
      await queryClient.invalidateQueries({ queryKey: workspaceInvitationsQueryKey(workspaceId) })
    },
  })
}

export function useDeleteInvitationMutation() {
  return useMutation(deleteInvitationMutationOptions(useQueryClient()))
}
