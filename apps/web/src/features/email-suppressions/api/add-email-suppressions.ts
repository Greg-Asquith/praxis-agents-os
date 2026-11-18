// apps/web/src/features/email-suppressions/api/add-email-suppressions.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { emailSuppressionsQueryKeys } from "@/features/email-suppressions/api/list-email-suppressions"
import type {
  EmailSuppressionAddRequest,
  EmailSuppressionAddResponse,
} from "@/features/email-suppressions/types"
import { apiRequest } from "@/lib/api/client"

export function useAddEmailSuppressionsMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (payload: EmailSuppressionAddRequest) =>
      apiRequest<EmailSuppressionAddResponse>("/email-suppressions/", {
        body: payload,
        method: "POST",
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: emailSuppressionsQueryKeys.workspace() })
    },
  })
}
