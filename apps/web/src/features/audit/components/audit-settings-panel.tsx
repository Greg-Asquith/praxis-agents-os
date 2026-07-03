// apps/web/src/features/audit/components/audit-settings-panel.tsx

import { useMemo, useState } from "react"
import { useSuspenseQuery } from "@tanstack/react-query"
import { FileClockIcon, ShieldAlertIcon } from "lucide-react"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyState } from "@/components/ui/empty-state"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { useAuditEventsQuery } from "@/features/audit/api/list-audit-events"
import { useSecurityEventsQuery } from "@/features/audit/api/list-security-events"
import { AuditEventDetail } from "@/features/audit/components/audit-event-detail"
import { AuditEventsTable } from "@/features/audit/components/audit-events-table"
import {
  AuditFilterBar,
  SecurityFilterBar,
  type AuditFilters,
  type SecurityFilters,
} from "@/features/audit/components/audit-filter-bar"
import { SecurityEventDetail } from "@/features/audit/components/security-event-detail"
import { SecurityEventsTable } from "@/features/audit/components/security-events-table"
import { useWorkspaceMembershipsQuery } from "@/features/workspaces/api/list-memberships"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { getErrorMessage } from "@/lib/api/errors"

const PAGE_SIZE = 50
const EMPTY_AUDIT_FILTERS: AuditFilters = {
  action: "",
  actorUserId: "",
  occurredAfter: "",
  occurredBefore: "",
  resourceType: "",
  status: "",
}
const EMPTY_SECURITY_FILTERS: SecurityFilters = {
  endpoint: "",
  eventType: "",
  ipAddress: "",
  occurredAfter: "",
  occurredBefore: "",
  userEmail: "",
}

export function AuditSettingsPanel() {
  const { data: user } = useSuspenseQuery(currentUserQueryOptions())

  if (!user.is_super_admin) {
    return <AuditEventsPanel />
  }

  return (
    <Tabs defaultValue="audit">
      <TabsList variant="line">
        <TabsTrigger value="audit">Audit Log</TabsTrigger>
        <TabsTrigger value="security">Security Events</TabsTrigger>
      </TabsList>
      <TabsContent value="audit">
        <AuditEventsPanel />
      </TabsContent>
      <TabsContent value="security">
        <SecurityEventsPanel />
      </TabsContent>
    </Tabs>
  )
}

function AuditEventsPanel() {
  const { workspace } = useActiveWorkspace()
  const membershipsQuery = useWorkspaceMembershipsQuery(workspace.id)
  const [filters, setFilters] = useState<AuditFilters>(EMPTY_AUDIT_FILTERS)
  const [offset, setOffset] = useState(0)
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const queryParams = useMemo(
    () => ({
      action: filters.action || undefined,
      actorUserId: filters.actorUserId || undefined,
      limit: PAGE_SIZE,
      offset,
      occurredAfter: filters.occurredAfter || undefined,
      occurredBefore: filters.occurredBefore || undefined,
      resourceType: filters.resourceType || undefined,
      status: filters.status || undefined,
    }),
    [filters, offset]
  )
  const eventsQuery = useAuditEventsQuery(queryParams)
  const eventsData = eventsQuery.data

  function updateFilters(nextFilters: AuditFilters) {
    setOffset(0)
    setFilters(nextFilters)
  }

  return (
    <Card className="border-0 bg-transparent shadow-none ring-0">
      <CardHeader>
        <CardTitle>Workspace events</CardTitle>
        <CardDescription>
          Review user and agent operations recorded for this workspace.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <AuditFilterBar
          filters={filters}
          memberships={membershipsQuery.data.memberships}
          onFiltersChange={updateFilters}
        />
        {eventsQuery.isError ? (
          <EmptyState
            description={getErrorMessage(eventsQuery.error)}
            icon={<FileClockIcon className="size-5" />}
            size="compact"
            title="Audit events could not load"
          />
        ) : (
          <AuditEventsTable
            events={eventsData?.events ?? []}
            isFetching={eventsQuery.isFetching}
            limit={eventsData?.limit ?? PAGE_SIZE}
            offset={eventsData?.offset ?? offset}
            total={eventsData?.total ?? 0}
            onPageChange={setOffset}
            onSelectEvent={setSelectedEventId}
          />
        )}
      </CardContent>
      <AuditEventDetail
        eventId={selectedEventId}
        onClose={() => {
          setSelectedEventId(null)
        }}
      />
    </Card>
  )
}

function SecurityEventsPanel() {
  const [filters, setFilters] = useState<SecurityFilters>(EMPTY_SECURITY_FILTERS)
  const [offset, setOffset] = useState(0)
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const queryParams = useMemo(
    () => ({
      endpoint: filters.endpoint || undefined,
      eventType: filters.eventType || undefined,
      ipAddress: filters.ipAddress || undefined,
      limit: PAGE_SIZE,
      offset,
      occurredAfter: filters.occurredAfter || undefined,
      occurredBefore: filters.occurredBefore || undefined,
      userEmail: filters.userEmail || undefined,
    }),
    [filters, offset]
  )
  const eventsQuery = useSecurityEventsQuery(queryParams, { enabled: true })
  const eventsData = eventsQuery.data

  function updateFilters(nextFilters: SecurityFilters) {
    setOffset(0)
    setFilters(nextFilters)
  }

  return (
    <Card className="border-0 bg-transparent shadow-none ring-0">
      <CardHeader>
        <CardTitle>Security events</CardTitle>
        <CardDescription>
          Review global authentication, rate-limit, and invitation security records.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <SecurityFilterBar filters={filters} onFiltersChange={updateFilters} />
        {eventsQuery.isError ? (
          <EmptyState
            description={getErrorMessage(eventsQuery.error)}
            icon={<ShieldAlertIcon className="size-5" />}
            size="compact"
            title="Security events could not load"
          />
        ) : (
          <SecurityEventsTable
            events={eventsData?.events ?? []}
            isFetching={eventsQuery.isFetching}
            limit={eventsData?.limit ?? PAGE_SIZE}
            offset={eventsData?.offset ?? offset}
            total={eventsData?.total ?? 0}
            onPageChange={setOffset}
            onSelectEvent={setSelectedEventId}
          />
        )}
      </CardContent>
      <SecurityEventDetail
        eventId={selectedEventId}
        onClose={() => {
          setSelectedEventId(null)
        }}
      />
    </Card>
  )
}
