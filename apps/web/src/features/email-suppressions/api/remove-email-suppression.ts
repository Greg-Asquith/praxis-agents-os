// apps/web/src/features/email-suppressions/api/remove-email-suppression.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { emailSuppressionsQueryKeys } from "@/features/email-suppressions/api/list-email-suppressions"
import { apiRequestNoContent } from "@/lib/api/client"

export function useRemoveEmailSuppressionMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (suppressionId: string) =>
      apiRequestNoContent(`/email-suppressions/${suppressionId}`, { method: "DELETE" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: emailSuppressionsQueryKeys.workspace() })
    },
  })
}
