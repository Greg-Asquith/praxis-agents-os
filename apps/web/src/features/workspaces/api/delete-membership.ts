// apps/web/src/features/workspaces/api/delete-membership.ts

import {
  mutationOptions,
  useMutation,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query"

import { workspaceMembershipsQueryOptions } from "@/features/workspaces/api/list-memberships"
import { apiRequestNoContent } from "@/lib/api/client"

export function deleteMembershipMutationOptions(queryClient: QueryClient) {
  return mutationOptions({
    mutationFn: ({ workspaceId, membershipId }: { workspaceId: string; membershipId: string }) =>
      apiRequestNoContent(`/workspaces/${workspaceId}/memberships/${membershipId}`, {
        method: "DELETE",
      }),
    onSuccess: async (_data, { workspaceId }) => {
      await queryClient.invalidateQueries({
        queryKey: workspaceMembershipsQueryOptions(workspaceId).queryKey,
      })
    },
  })
}

export function useDeleteMembershipMutation() {
  return useMutation(deleteMembershipMutationOptions(useQueryClient()))
}
