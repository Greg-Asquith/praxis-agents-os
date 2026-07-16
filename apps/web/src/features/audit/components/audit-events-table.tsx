// apps/web/src/features/audit/components/audit-events-table.tsx

import { FileClockIcon } from "lucide-react"

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
import type { AuditEvent } from "@/features/audit/types"
import { useToolLabels } from "@/features/tools/use-tool-labels"
import { formatDateTime, titleCaseToken, truncateForPreview } from "@/lib/format"

export function AuditEventsTable({
  events,
  isFetching,
  limit,
  offset,
  onPageChange,
  onSelectEvent,
  total,
}: {
  events: AuditEvent[]
  isFetching: boolean
  limit: number
  offset: number
  onPageChange: (offset: number) => void
  onSelectEvent: (eventId: string) => void
  total: number
}) {
  const toolLabelFor = useToolLabels()

  if (events.length === 0) {
    return (
      <EmptyState
        description="Audit events for this workspace will appear here after users or agents make changes."
        icon={<FileClockIcon className="size-5" />}
        size="compact"
        title={isFetching ? "Loading audit events" : "No audit events found"}
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <ResponsiveList>
        {events.map((event) => (
          <AuditEventMobileRow
            key={event.id}
            event={event}
            onSelectEvent={onSelectEvent}
            toolLabelFor={toolLabelFor}
          />
        ))}
      </ResponsiveList>

      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Occurred</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Resource</TableHead>
              <TableHead>Tool</TableHead>
              <TableHead>Provider</TableHead>
              <TableHead>Actor</TableHead>
              <TableHead>Summary</TableHead>
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
                  <div className="flex items-center gap-2">
                    <span>{titleCaseToken(event.action, event.action)}</span>
                    <StatusBadge status={event.status} />
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex max-w-64 flex-col gap-1">
                    <span>{resourceLabel(event, toolLabelFor)}</span>
                    {resourceMeta(event) ? (
                      <span className="text-muted-foreground truncate text-xs">
                        {resourceMeta(event)}
                      </span>
                    ) : null}
                  </div>
                </TableCell>
                <TableCell>
                  {event.tool_name ? (
                    <span className="block max-w-48 truncate">{toolLabelFor(event.tool_name)}</span>
                  ) : (
                    <span className="text-muted-foreground">-</span>
                  )}
                </TableCell>
                <TableCell>
                  {event.tool_provider ? (
                    titleCaseToken(event.tool_provider, event.tool_provider)
                  ) : (
                    <span className="text-muted-foreground">-</span>
                  )}
                </TableCell>
                <TableCell>
                  {event.actor_display ?? titleCaseToken(event.actor_type, "Actor")}
                </TableCell>
                <TableCell>
                  <span className="block max-w-72 truncate">
                    {truncateForPreview(event.summary, 120)}
                  </span>
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

function AuditEventMobileRow({
  event,
  onSelectEvent,
  toolLabelFor,
}: {
  event: AuditEvent
  onSelectEvent: (eventId: string) => void
  toolLabelFor: (toolName: string) => string
}) {
  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate font-medium">{event.summary}</p>
            <p className="text-muted-foreground truncate text-xs">
              {formatDateTime(event.occurred_at)}
            </p>
          </div>
          <StatusBadge status={event.status} />
        </div>

        <dl className="grid gap-3 sm:grid-cols-2">
          <ResponsiveListMeta label="Action">
            {titleCaseToken(event.action, event.action)}
          </ResponsiveListMeta>
          <ResponsiveListMeta label="Resource">
            {resourceLabel(event, toolLabelFor)}
          </ResponsiveListMeta>
          {event.tool_name ? (
            <ResponsiveListMeta label="Tool">{toolLabelFor(event.tool_name)}</ResponsiveListMeta>
          ) : null}
          {event.tool_provider ? (
            <ResponsiveListMeta label="Provider">
              {titleCaseToken(event.tool_provider, event.tool_provider)}
            </ResponsiveListMeta>
          ) : null}
          <ResponsiveListMeta label="Actor">
            {event.actor_display ?? titleCaseToken(event.actor_type, "Actor")}
          </ResponsiveListMeta>
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

function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant={status === "failure" || status === "denied" ? "destructive" : "secondary"}>
      {titleCaseToken(status, status)}
    </Badge>
  )
}

function resourceLabel(event: AuditEvent, toolLabelFor: (toolName: string) => string) {
  if (event.resource_type === "tool_call" && event.tool_name) {
    return `${titleCaseToken(event.resource_type, event.resource_type)} ${toolLabelFor(
      event.tool_name
    )}`
  }
  return titleCaseToken(event.resource_type, event.resource_type)
}

function resourceMeta(event: AuditEvent) {
  if (event.resource_type === "tool_call") {
    return event.tool_name ?? event.resource_id
  }
  return event.resource_id
}
