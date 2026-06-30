// apps/web/src/features/auth/api/get-identities.ts

import { queryOptions } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import type { IdentitiesResponse } from "@/features/auth/types"

export const identitiesQueryKey = ["auth", "identities"] as const

async function getIdentities() {
  return apiRequest<IdentitiesResponse>("/auth/me/identities")
}

export function identitiesQueryOptions() {
  return queryOptions({
    queryKey: identitiesQueryKey,
    queryFn: getIdentities,
    staleTime: 60_000,
  })
}
