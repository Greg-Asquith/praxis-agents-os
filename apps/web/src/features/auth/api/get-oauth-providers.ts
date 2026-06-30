// apps/web/src/features/auth/api/get-oauth-providers.ts

import { queryOptions } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import type { AuthProvidersResponse } from "@/features/auth/types"

export const oauthProvidersQueryKey = ["auth", "oauth-providers"] as const

async function getOauthProviders() {
  return apiRequest<AuthProvidersResponse>("/auth/oauth/providers")
}

export function oauthProvidersQueryOptions() {
  return queryOptions({
    queryKey: oauthProvidersQueryKey,
    queryFn: getOauthProviders,
    staleTime: 5 * 60_000,
  })
}
