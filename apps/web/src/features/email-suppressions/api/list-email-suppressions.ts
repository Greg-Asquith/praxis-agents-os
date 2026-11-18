// apps/web/src/features/email-suppressions/api/list-email-suppressions.ts

import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query"

import type { EmailSuppressionListResponse } from "@/features/email-suppressions/types"
import { apiRequest } from "@/lib/api/client"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

type ListEmailSuppressionsParams = {
  limit: number
  offset: number
  search: string
}

export const emailSuppressionsQueryKeys = createWorkspaceScopedQueryKeys("email-suppressions")

function emailSuppressionsQueryOptions(params: ListEmailSuppressionsParams) {
  return queryOptions({
    queryKey: emailSuppressionsQueryKeys.list(params),
    queryFn: () =>
      apiRequest<EmailSuppressionListResponse>("/email-suppressions/", {
        query: {
          limit: params.limit,
          offset: params.offset,
          search: params.search || undefined,
        },
      }),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  })
}

export function useEmailSuppressionsQuery(params: ListEmailSuppressionsParams) {
  return useQuery(emailSuppressionsQueryOptions(params))
}
