// apps/web/src/features/auth/api/get-current-user.ts

import { queryOptions, type QueryClient } from "@tanstack/react-query"

import { apiRequest, reportSessionLoss } from "@/lib/api/client"
import { ApiError } from "@/lib/api/errors"
import type { AuthUser } from "@/features/auth/types"

export const currentUserQueryKey = ["auth", "me"] as const

async function getCurrentUser() {
  return apiRequest<AuthUser>("/auth/me")
}

async function getOptionalCurrentUserRequest() {
  return apiRequest<AuthUser>("/auth/me", { sessionPolicy: "optional" })
}

export function currentUserQueryOptions() {
  return queryOptions({
    queryKey: currentUserQueryKey,
    queryFn: getCurrentUser,
    retry: false,
    staleTime: 60_000,
  })
}

export async function getOptionalCurrentUser(queryClient: QueryClient) {
  const hadAuthenticatedUser = queryClient.getQueryData(currentUserQueryKey) !== undefined

  try {
    return await queryClient.fetchQuery({
      ...currentUserQueryOptions(),
      queryFn: getOptionalCurrentUserRequest,
    })
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      if (hadAuthenticatedUser) {
        reportSessionLoss()
      }
      return null
    }
    if (error instanceof TypeError) {
      return null
    }
    throw error
  }
}
