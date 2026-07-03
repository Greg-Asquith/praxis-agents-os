// apps/web/src/features/audit/api/get-security-event.ts

import { queryOptions, useQuery } from "@tanstack/react-query"

import { securityEventsQueryKeys } from "@/features/audit/api/list-security-events"
import type { SecurityEvent } from "@/features/audit/types"
import { apiRequest } from "@/lib/api/client"

const DISABLED_SECURITY_EVENT_DETAIL_QUERY_KEY = ["security-events", "detail", "disabled"] as const

async function getSecurityEvent(eventId: string) {
  return apiRequest<SecurityEvent>(`/security-events/${eventId}`)
}

function securityEventQueryOptions(eventId: string | null) {
  return queryOptions({
    queryKey: eventId
      ? securityEventsQueryKeys.detail(eventId)
      : DISABLED_SECURITY_EVENT_DETAIL_QUERY_KEY,
    queryFn: () => getSecurityEvent(eventId ?? ""),
    enabled: eventId !== null,
    staleTime: 15_000,
  })
}

export function useSecurityEventQuery(eventId: string | null) {
  return useQuery(securityEventQueryOptions(eventId))
}
