// apps/web/src/features/audit/components/security-event-detail.tsx

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useSecurityEventQuery } from "@/features/audit/api/get-security-event"
import type { SecurityEvent } from "@/features/audit/types"
import { JsonBlock } from "@/features/conversations/components/tool-call-content-blocks"
import { getErrorMessage } from "@/lib/api/errors"
import { formatDateTime, titleCaseToken } from "@/lib/format"

export function SecurityEventDetail({
  eventId,
  onClose,
}: {
  eventId: string | null
  onClose: () => void
}) {
  const eventQuery = useSecurityEventQuery(eventId)
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
          <DialogTitle>Security event</DialogTitle>
          <DialogDescription>
            {event ? formatDateTime(event.occurred_at) : "Loading event details"}
          </DialogDescription>
        </DialogHeader>

        {event ? (
          <SecurityEventFields event={event} />
        ) : (
          <p className="text-muted-foreground text-sm">
            {eventQuery.isError ? getErrorMessage(eventQuery.error) : "Loading event details."}
          </p>
        )}
      </DialogContent>
    </Dialog>
  )
}

function SecurityEventFields({ event }: { event: SecurityEvent }) {
  return (
    <div className="flex flex-col gap-4">
      <dl className="grid gap-3 md:grid-cols-2">
        <DetailField label="Event" value={titleCaseToken(event.event_type, event.event_type)} />
        <DetailField label="User email" value={event.user_email ?? "None"} />
        <DetailField label="IP address" value={event.ip_address} />
        <DetailField label="Endpoint" value={event.endpoint ?? "None"} />
        <DetailField label="Request ID" value={event.request_id ?? "None"} />
        <DetailField label="User agent" value={event.user_agent ?? "None"} />
        <DetailField label="Created" value={formatDateTime(event.created_at)} />
      </dl>
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
