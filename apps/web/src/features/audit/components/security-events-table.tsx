// apps/web/src/features/audit/components/security-events-table.tsx

import { ShieldAlertIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { PaginationControls } from "@/components/ui/pagination-controls"
import {
  ResponsiveList,
  ResponsiveListItem,
  ResponsiveListMeta,
} from "@/components/ui/responsive-list"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { SecurityEvent } from "@/features/audit/types"
import { formatDateTime, titleCaseToken } from "@/lib/format"

export function SecurityEventsTable({
  events,
  isFetching,
  limit,
  offset,
  onPageChange,
  onSelectEvent,
  total,
}: {
  events: SecurityEvent[]
  isFetching: boolean
  limit: number
  offset: number
  onPageChange: (offset: number) => void
  onSelectEvent: (eventId: string) => void
  total: number
}) {
  if (events.length === 0) {
    return (
      <EmptyState
        description="Global security events will appear here after authentication, rate-limit, or invitation activity."
        icon={<ShieldAlertIcon className="size-5" />}
        size="compact"
        title={isFetching ? "Loading security events" : "No security events found"}
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <ResponsiveList>
        {events.map((event) => (
          <SecurityEventMobileRow key={event.id} event={event} onSelectEvent={onSelectEvent} />
        ))}
      </ResponsiveList>

      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Occurred</TableHead>
              <TableHead>Event</TableHead>
              <TableHead>User</TableHead>
              <TableHead>IP address</TableHead>
              <TableHead>Endpoint</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {events.map((event) => (
              <TableRow
                key={event.id}
                className="cursor-pointer"
                tabIndex={0}
                onClick={() => {
                  onSelectEvent(event.id)
                }}
                onKeyDown={(keyboardEvent) => {
                  if (keyboardEvent.key === "Enter" || keyboardEvent.key === " ") {
                    keyboardEvent.preventDefault()
                    onSelectEvent(event.id)
                  }
                }}
              >
                <TableCell>{formatDateTime(event.occurred_at)}</TableCell>
                <TableCell>
                  <Badge variant="outline">
                    {titleCaseToken(event.event_type, event.event_type)}
                  </Badge>
                </TableCell>
                <TableCell>{event.user_email ?? "None"}</TableCell>
                <TableCell>{event.ip_address}</TableCell>
                <TableCell>
                  <span className="block max-w-72 truncate">{event.endpoint ?? "None"}</span>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <PaginationControls limit={limit} offset={offset} onPageChange={onPageChange} total={total} />
    </div>
  )
}

function SecurityEventMobileRow({
  event,
  onSelectEvent,
}: {
  event: SecurityEvent
  onSelectEvent: (eventId: string) => void
}) {
  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="min-w-0">
          <p className="truncate font-medium">
            {titleCaseToken(event.event_type, event.event_type)}
          </p>
          <p className="text-muted-foreground truncate text-xs">
            {formatDateTime(event.occurred_at)}
          </p>
        </div>

        <dl className="grid gap-3 sm:grid-cols-2">
          <ResponsiveListMeta label="User">{event.user_email ?? "None"}</ResponsiveListMeta>
          <ResponsiveListMeta label="IP address">{event.ip_address}</ResponsiveListMeta>
          <ResponsiveListMeta label="Endpoint">{event.endpoint ?? "None"}</ResponsiveListMeta>
        </dl>

        <Button
          className="w-full"
          onClick={() => {
            onSelectEvent(event.id)
          }}
          type="button"
          variant="outline"
        >
          View Details
        </Button>
      </div>
    </ResponsiveListItem>
  )
}
