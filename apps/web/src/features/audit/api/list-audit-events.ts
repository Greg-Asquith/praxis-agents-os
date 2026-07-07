// apps/web/src/features/audit/api/list-audit-events.ts

import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query"

import type { AuditEventsListResponse } from "@/features/audit/types"
import { createWorkspaceScopedQueryKeys } from "@/features/workspaces/query-keys"
import { apiRequest } from "@/lib/api/client"

export type ListAuditEventsParams = {
  action?: string | undefined
  actorUserId?: string | undefined
  limit?: number | undefined
  offset?: number | undefined
  occurredAfter?: string | undefined
  occurredBefore?: string | undefined
  resourceId?: string | undefined
  resourceType?: string | undefined
  status?: string | undefined
}

export const auditEventsQueryKeys = createWorkspaceScopedQueryKeys("audit-events")

async function listAuditEvents({
  action,
  actorUserId,
  limit = 50,
  offset = 0,
  occurredAfter,
  occurredBefore,
  resourceId,
  resourceType,
  status,
}: ListAuditEventsParams = {}) {
  return apiRequest<AuditEventsListResponse>("/audit-events/", {
    query: {
      action,
      actor_user_id: actorUserId,
      limit,
      offset,
      occurred_after: toApiDateTime(occurredAfter),
      occurred_before: toApiDateTime(occurredBefore),
      resource_id: resourceId,
      resource_type: resourceType,
      status,
    },
  })
}

function auditEventsQueryOptions(params: ListAuditEventsParams = {}) {
  return queryOptions({
    queryKey: auditEventsQueryKeys.list(params),
    queryFn: () => listAuditEvents(params),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  })
}

export function useAuditEventsQuery(params: ListAuditEventsParams = {}) {
  return useQuery(auditEventsQueryOptions(params))
}

function toApiDateTime(value: string | undefined) {
  return value ? new Date(value).toISOString() : undefined
}
