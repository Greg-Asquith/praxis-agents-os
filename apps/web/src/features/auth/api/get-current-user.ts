// apps/web/src/features/auth/api/get-current-user.ts

import { queryOptions, type QueryClient } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import { ApiError } from "@/lib/api/errors"
import type { AuthUser } from "@/features/auth/types"

export const currentUserQueryKey = ["auth", "me"] as const

async function getCurrentUser() {
  return apiRequest<AuthUser>("/auth/me")
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
  try {
    return await queryClient.ensureQueryData(currentUserQueryOptions())
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null
    }
    if (error instanceof TypeError) {
      return null
    }
    throw error
  }
}
