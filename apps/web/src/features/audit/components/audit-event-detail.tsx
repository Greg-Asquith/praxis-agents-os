// apps/web/src/features/audit/components/audit-event-detail.tsx

import type { ReactNode } from "react"
import { ChevronDownIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { JsonBlock } from "@/features/conversations/components/tool-call-content-blocks"
import { useAuditEventQuery } from "@/features/audit/api/get-audit-event"
import { IntegrationOperationDetail } from "@/features/audit/components/integration-operation-detail"
import { parseIntegrationOperationDetail } from "@/features/audit/operation-detail"
import type { AuditEvent } from "@/features/audit/types"
import { useToolLabels } from "@/features/tools/use-tool-labels"
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
  const toolLabelFor = useToolLabels()

  return (
    <Dialog
      open={eventId !== null}
      onOpenChange={(open) => {
        if (!open) {
          onClose()
        }
      }}
    >
      <DialogContent className="max-h-[calc(100dvh-2rem)] grid-rows-[auto_minmax(0,1fr)] gap-0 overflow-hidden p-0 sm:max-w-2xl">
        <DialogHeader className="border-b px-5 py-4 pr-12">
          <div className="flex min-w-0 items-center gap-2">
            <DialogTitle className="truncate">
              {event?.tool_name ? toolLabelFor(event.tool_name) : "Audit event"}
            </DialogTitle>
            {event ? <EventStatusBadge status={event.status} /> : null}
          </div>
          <DialogDescription>
            {event
              ? [
                  event.tool_provider
                    ? titleCaseToken(event.tool_provider, event.tool_provider)
                    : null,
                  formatDateTime(event.occurred_at),
                ]
                  .filter(Boolean)
                  .join(" · ")
              : "Loading event details"}
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 overflow-y-auto overscroll-contain px-5 py-4">
          {event ? (
            <AuditEventFields event={event} toolLabelFor={toolLabelFor} />
          ) : (
            <p className="text-muted-foreground text-sm">
              {eventQuery.isError ? getErrorMessage(eventQuery.error) : "Loading event details."}
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function AuditEventFields({
  event,
  toolLabelFor,
}: {
  event: AuditEvent
  toolLabelFor: (toolName: string) => string
}) {
  const args = event.details["args"]
  const operationDetail = event.details["operation_detail"]

  const hasOperationDetail = parseIntegrationOperationDetail(operationDetail) !== null

  return (
    <div className="flex flex-col gap-5">
      {hasOperationDetail ? <IntegrationOperationDetail value={operationDetail} /> : null}
      {hasOperationDetail ? null : <EventSummary summary={event.summary} />}
      {hasOperationDetail ? null : <EventFields event={event} toolLabelFor={toolLabelFor} />}
      <TechnicalDetails event={event} showSummary={hasOperationDetail} toolLabelFor={toolLabelFor}>
        {args === undefined ? null : <JsonBlock label="Arguments" value={args} />}
        <JsonBlock label="Raw event data" value={event.details} />
      </TechnicalDetails>
    </div>
  )
}

function EventSummary({ summary }: { summary: string }) {
  return (
    <div className="min-w-0">
      <p className="text-muted-foreground mb-1.5 text-xs font-medium">Summary</p>
      <p className="bg-muted/40 rounded-lg border p-3 text-sm leading-relaxed wrap-break-word">
        {summary}
      </p>
    </div>
  )
}

function EventFields({
  event,
  toolLabelFor,
}: {
  event: AuditEvent
  toolLabelFor: (toolName: string) => string
}) {
  return (
    <dl className="grid gap-3 sm:grid-cols-2">
      <DetailField label="Action" value={titleCaseToken(event.action, event.action)} />
      <DetailField label="Resource" value={resourceValue(event, toolLabelFor)} />
      {event.tool_name ? <DetailField label="Tool" value={toolLabelFor(event.tool_name)} /> : null}
      <DetailField label="Actor" value={event.actor_display ?? event.actor_type} />
    </dl>
  )
}

function TechnicalDetails({
  children,
  event,
  showSummary,
  toolLabelFor,
}: {
  children: ReactNode
  event: AuditEvent
  showSummary: boolean
  toolLabelFor: (toolName: string) => string
}) {
  return (
    <details className="group min-w-0 rounded-lg border">
      <summary className="focus-visible:ring-ring flex cursor-pointer list-none items-center justify-between gap-3 rounded-lg px-3.5 py-3 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-offset-2 [&::-webkit-details-marker]:hidden">
        Technical details
        <ChevronDownIcon
          aria-hidden="true"
          className="text-muted-foreground size-4 transition-transform group-open:rotate-180"
        />
      </summary>
      <div className="min-w-0 space-y-4 border-t p-3.5">
        {showSummary ? <EventSummary summary={event.summary} /> : null}
        <dl className="grid gap-3 sm:grid-cols-2">
          <DetailField label="Action" value={titleCaseToken(event.action, event.action)} />
          <DetailField label="Status" value={titleCaseToken(event.status, event.status)} />
          <DetailField label="Resource" value={resourceValue(event, toolLabelFor)} />
          <DetailField label="Actor" value={event.actor_display ?? event.actor_type} />
          {event.actor_user_id ? (
            <DetailField label="Actor user ID" value={event.actor_user_id} mono />
          ) : null}
          {event.requested_by_user_id ? (
            <DetailField label="Requested by" value={event.requested_by_user_id} mono />
          ) : null}
          {event.request_id ? (
            <DetailField label="Request ID" value={event.request_id} mono />
          ) : null}
          {event.ip_address ? <DetailField label="IP address" value={event.ip_address} /> : null}
          {event.user_agent ? <DetailField label="User agent" value={event.user_agent} /> : null}
          <DetailField label="Recorded" value={formatDateTime(event.created_at)} />
        </dl>
        {children}
      </div>
    </details>
  )
}

function DetailField({
  label,
  mono = false,
  value,
}: {
  label: string
  mono?: boolean
  value: string
}) {
  return (
    <div className="min-w-0">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className={mono ? "mt-1 font-mono text-xs break-all" : "mt-1 text-sm wrap-break-word"}>
        {value}
      </dd>
    </div>
  )
}

function EventStatusBadge({ status }: { status: string }) {
  const variant =
    status === "failure" || status === "denied"
      ? "destructive"
      : status === "success"
        ? "success"
        : status === "unverified"
          ? "warning"
          : "secondary"
  return <Badge variant={variant}>{titleCaseToken(status, status)}</Badge>
}

function resourceValue(event: AuditEvent, toolLabelFor: (toolName: string) => string) {
  const label = titleCaseToken(event.resource_type, event.resource_type)
  if (event.resource_type === "tool_call" && event.tool_name) {
    return `${label} ${toolLabelFor(event.tool_name)}`
  }
  return `${label}${event.resource_id ? ` ${event.resource_id}` : ""}`
}
