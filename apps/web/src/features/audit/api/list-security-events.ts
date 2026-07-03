// apps/web/src/features/audit/api/list-security-events.ts

import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query"

import type { SecurityEventsListResponse } from "@/features/audit/types"
import { apiRequest } from "@/lib/api/client"

export type ListSecurityEventsParams = {
  endpoint?: string | undefined
  eventType?: string | undefined
  ipAddress?: string | undefined
  limit?: number | undefined
  offset?: number | undefined
  occurredAfter?: string | undefined
  occurredBefore?: string | undefined
  userEmail?: string | undefined
}

export const securityEventsQueryKeys = {
  all: ["security-events"] as const,
  details: () => [...securityEventsQueryKeys.all, "detail"] as const,
  detail: (eventId: string) => [...securityEventsQueryKeys.details(), eventId] as const,
  lists: () => [...securityEventsQueryKeys.all, "list"] as const,
  list: (params: ListSecurityEventsParams = {}) =>
    [...securityEventsQueryKeys.lists(), params] as const,
}

async function listSecurityEvents({
  endpoint,
  eventType,
  ipAddress,
  limit = 50,
  offset = 0,
  occurredAfter,
  occurredBefore,
  userEmail,
}: ListSecurityEventsParams = {}) {
  return apiRequest<SecurityEventsListResponse>("/security-events/", {
    query: {
      endpoint,
      event_type: eventType,
      ip_address: ipAddress,
      limit,
      offset,
      occurred_after: toApiDateTime(occurredAfter),
      occurred_before: toApiDateTime(occurredBefore),
      user_email: userEmail,
    },
  })
}

function securityEventsQueryOptions(
  params: ListSecurityEventsParams = {},
  options: { enabled: boolean }
) {
  return queryOptions({
    queryKey: securityEventsQueryKeys.list(params),
    queryFn: () => listSecurityEvents(params),
    enabled: options.enabled,
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  })
}

export function useSecurityEventsQuery(
  params: ListSecurityEventsParams = {},
  options: { enabled: boolean }
) {
  return useQuery(securityEventsQueryOptions(params, options))
}

function toApiDateTime(value: string | undefined) {
  return value ? new Date(value).toISOString() : undefined
}
