// apps/web/src/features/audit/api/get-audit-event.ts

import { queryOptions, useQuery } from "@tanstack/react-query"

import { auditEventsQueryKeys } from "@/features/audit/api/list-audit-events"
import type { AuditEvent } from "@/features/audit/types"
import { apiRequest } from "@/lib/api/client"

const DISABLED_AUDIT_EVENT_DETAIL_QUERY_KEY = ["audit-events", "detail", "disabled"] as const

async function getAuditEvent(eventId: string) {
  return apiRequest<AuditEvent>(`/audit-events/${eventId}`)
}

function auditEventQueryOptions(eventId: string | null) {
  return queryOptions({
    queryKey: eventId
      ? auditEventsQueryKeys.detail(eventId)
      : DISABLED_AUDIT_EVENT_DETAIL_QUERY_KEY,
    queryFn: () => getAuditEvent(eventId ?? ""),
    enabled: eventId !== null,
    staleTime: 15_000,
  })
}

export function useAuditEventQuery(eventId: string | null) {
  return useQuery(auditEventQueryOptions(eventId))
}
