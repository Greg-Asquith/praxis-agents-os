// apps/web/src/features/audit/components/audit-event-detail.tsx

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { JsonBlock } from "@/features/conversations/components/tool-call-content-blocks"
import { useAuditEventQuery } from "@/features/audit/api/get-audit-event"
import type { AuditEvent } from "@/features/audit/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formatDateTime, titleCaseToken } from "@/lib/format"

export function AuditEventDetail({
  eventId,
  onClose,
}: {
  eventId: string | null
  onClose: () => void
}) {
  const eventQuery = useAuditEventQuery(eventId)
  const event = eventQuery.data ?? null

  return (
    <Dialog
      open={eventId !== null}
      onOpenChange={(open) => {
        if (!open) {
          onClose()
        }
      }}
    >
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Audit event</DialogTitle>
          <DialogDescription>
            {event ? formatDateTime(event.occurred_at) : "Loading event details"}
          </DialogDescription>
        </DialogHeader>

        {event ? (
          <AuditEventFields event={event} />
        ) : (
          <p className="text-muted-foreground text-sm">
            {eventQuery.isError ? getErrorMessage(eventQuery.error) : "Loading event details."}
          </p>
        )}
      </DialogContent>
    </Dialog>
  )
}

function AuditEventFields({ event }: { event: AuditEvent }) {
  const args = event.details["args"]

  return (
    <div className="flex flex-col gap-4">
      <dl className="grid gap-3 md:grid-cols-2">
        <DetailField label="Action" value={titleCaseToken(event.action, event.action)} />
        <DetailField label="Status" value={titleCaseToken(event.status, event.status)} />
        <DetailField label="Resource" value={resourceValue(event)} />
        {event.tool_name ? <DetailField label="Tool" value={event.tool_name} /> : null}
        {event.tool_provider ? <DetailField label="Provider" value={event.tool_provider} /> : null}
        <DetailField label="Actor" value={event.actor_display ?? event.actor_type} />
        <DetailField label="Actor user ID" value={event.actor_user_id ?? "None"} />
        <DetailField label="Requested by" value={event.requested_by_user_id ?? "None"} />
        <DetailField label="Request ID" value={event.request_id ?? "None"} />
        <DetailField label="IP address" value={event.ip_address ?? "None"} />
        <DetailField label="User agent" value={event.user_agent ?? "None"} />
        <DetailField label="Created" value={formatDateTime(event.created_at)} />
      </dl>
      <div className="min-w-0">
        <p className="text-muted-foreground mb-1 text-xs font-medium">Summary</p>
        <p className="bg-muted/50 rounded-md p-2 text-sm leading-relaxed wrap-break-word">
          {event.summary}
        </p>
      </div>
      {args === undefined ? null : <JsonBlock label="Arguments" value={args} />}
      <JsonBlock label="Details" value={event.details} />
    </div>
  )
}

function DetailField({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="mt-1 truncate text-sm">{value}</dd>
    </div>
  )
}

function resourceValue(event: AuditEvent) {
  const label = titleCaseToken(event.resource_type, event.resource_type)
  if (event.resource_type === "tool_call" && event.tool_name) {
    return `${label} ${event.tool_name}`
  }
  return `${label}${event.resource_id ? ` ${event.resource_id}` : ""}`
}
