// apps/web/src/features/audit/components/integration-operation-detail.tsx

import { useMemo, useState } from "react"
import {
  CircleAlertIcon,
  CircleCheckIcon,
  CircleXIcon,
  Clock3Icon,
  MinusCircleIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { paginateItems, PaginationControls } from "@/components/ui/pagination-controls"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import {
  parseIntegrationOperationDetail,
  type AuditDetailValue,
  type OperationCounts,
  type OperationDetail,
  type OperationIntentGroup,
  type OperationOutcome,
  type OperationOutcomeStatus,
} from "@/features/audit/operation-detail"
import { titleCaseToken, truncateText } from "@/lib/format"

const STRUCTURED_VALUE_PREVIEW_LENGTH = 15
const AUDIT_DETAIL_PAGE_SIZE = 25

export function IntegrationOperationDetail({
  eventId,
  value,
}: {
  eventId: string
  value: unknown
}) {
  const detail = parseIntegrationOperationDetail(value)
  if (!detail) return null

  return <IntegrationOperationDetailContent detail={detail} key={eventId} />
}

function IntegrationOperationDetailContent({ detail }: { detail: OperationDetail }) {
  const targetAttributes = Object.entries(detail.target.attributes).filter(
    ([, item]) => item !== null
  )

  return (
    <section className="min-w-0 space-y-5" aria-label="Integration operation evidence">
      {detail.phase === "pending" ? (
        <PendingSummary itemCount={intentItemCount(detail)} />
      ) : (
        <OperationOutcome intentCounts={detail.intent_counts} effectCounts={detail.effect_counts} />
      )}

      <div className="space-y-2">
        <SectionLabel>Target</SectionLabel>
        <div className="text-sm">
          <div className="flex min-w-0 items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="font-medium wrap-break-word">
                {detail.target.display_name ?? detail.target.external_id}
              </p>
              <p className="text-muted-foreground mt-0.5 text-xs">
                {titleCaseToken(detail.target.entity_type, detail.target.entity_type)}
              </p>
            </div>
            <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
              ID {detail.target.external_id}
            </span>
          </div>
          {targetAttributes.length > 0 ? (
            <dl className="mt-2 grid gap-x-4 gap-y-1.5 sm:grid-cols-2 md:grid-cols-3">
              {targetAttributes.map(([key, item]) => (
                <DetailField key={key} label={key} value={item} />
              ))}
            </dl>
          ) : null}
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <SectionLabel>
            {detail.phase === "pending" ? "Requested changes" : "Outcomes"}
          </SectionLabel>
          <span className="text-muted-foreground text-xs tabular-nums">
            {intentItemCount(detail)} {intentItemCount(detail) === 1 ? "item" : "items"}
          </span>
        </div>
        <PaginatedIntentItems detail={detail} />
      </div>
    </section>
  )
}

type IntentItemRow = {
  group: OperationIntentGroup
  groupIndex: number
  itemIndex: number
  outcome: OperationOutcome | undefined
}
type IntentItemSegment = [IntentItemRow, ...IntentItemRow[]]

function PaginatedIntentItems({ detail }: { detail: OperationDetail }) {
  const [pageOffset, setPageOffset] = useState(0)
  const rows = useMemo(
    () =>
      detail.intent_groups.flatMap((group, groupIndex) =>
        group.items.map((_, itemIndex) => ({
          group,
          groupIndex,
          itemIndex,
          outcome:
            detail.phase === "terminal"
              ? detail.outcome_groups[groupIndex]?.outcomes[itemIndex]
              : undefined,
        }))
      ),
    [detail]
  )
  const page = paginateItems(rows, pageOffset, AUDIT_DETAIL_PAGE_SIZE)
  const segments = segmentIntentRows(page.items)

  return (
    <div className="space-y-3">
      <div className="max-h-[min(28rem,50dvh)] divide-y overflow-y-auto rounded-lg border">
        {segments.map((segment) => (
          <IntentGroup
            group={segment[0].group}
            groupIndex={segment[0].groupIndex}
            key={`${segment[0].group.key}:${String(segment[0].itemIndex)}`}
            rows={segment}
          />
        ))}
      </div>
      {rows.length > AUDIT_DETAIL_PAGE_SIZE ? (
        <PaginationControls
          ariaLabel={
            detail.phase === "pending" ? "Requested changes pagination" : "Outcomes pagination"
          }
          limit={AUDIT_DETAIL_PAGE_SIZE}
          offset={page.offset}
          onPageChange={setPageOffset}
          total={rows.length}
        />
      ) : null}
    </div>
  )
}

function PendingSummary({ itemCount }: { itemCount: number }) {
  return (
    <div className="flex items-start gap-3 py-1">
      <div className="text-muted-foreground pt-0.5">
        <Clock3Icon className="size-4" aria-hidden="true" />
      </div>
      <div className="min-w-0">
        <p className="font-medium">Waiting to record the provider outcome</p>
        <p className="text-muted-foreground mt-1 text-xs">
          {itemCount} {itemCount === 1 ? "requested item is" : "requested items are"} recorded. No
          outcome is claimed yet.
        </p>
      </div>
    </div>
  )
}

function OperationOutcome({
  intentCounts,
  effectCounts,
}: {
  intentCounts: OperationCounts
  effectCounts: OperationCounts
}) {
  const state = aggregateState(intentCounts, effectCounts)
  const Icon =
    state === "unverified"
      ? CircleAlertIcon
      : state === "failure"
        ? CircleXIcon
        : state === "success"
          ? CircleCheckIcon
          : MinusCircleIcon
  const title =
    state === "unverified"
      ? "One or more outcomes could not be verified"
      : state === "failure"
        ? "The requested changes failed"
        : state === "partial"
          ? "Some requested changes failed"
          : intentCounts.applied > 0
            ? "Requested changes completed"
            : "No provider changes were needed"
  return (
    <div className="flex items-start gap-3 py-1">
      <div
        className={
          state === "failure"
            ? "text-destructive pt-0.5"
            : state === "partial" || state === "unverified"
              ? "text-warning pt-0.5"
              : "text-success pt-0.5"
        }
      >
        <Icon className="size-4" aria-hidden="true" />
      </div>
      <div className="min-w-0 space-y-2">
        <p className="flex gap-4 font-medium">
          {title} <StatusCounts counts={intentCounts} />
        </p>
      </div>
    </div>
  )
}

function StatusCounts({ counts }: { counts: OperationCounts }) {
  const nonZero = (["applied", "skipped", "failed", "unverified"] as const).filter(
    (status) => counts[status] > 0
  )
  return (
    <div className="flex flex-wrap gap-1.5" aria-label="Outcome counts">
      {nonZero.map((status) => (
        <StatusBadge count={counts[status]} key={status} status={status} />
      ))}
    </div>
  )
}

function IntentGroup({
  group,
  groupIndex,
  rows,
}: {
  group: OperationIntentGroup
  groupIndex: number
  rows: IntentItemRow[]
}) {
  const groupFields = visibleGroupFields(group)
  return (
    <article className="min-w-0">
      <div className="bg-muted/30 flex min-w-0 items-center gap-2 px-3.5 py-2.5">
        <span className="text-muted-foreground text-xs tabular-nums">{groupIndex + 1}</span>
        <Badge variant="outline">{titleCaseToken(group.action, group.action)}</Badge>
        <span className="truncate text-sm font-medium">
          {group.display_name ?? titleCaseToken(group.entity_type, group.entity_type)}
        </span>
        {group.external_id ? (
          <span className="text-muted-foreground ml-auto text-[11px]">ID {group.external_id}</span>
        ) : null}
      </div>
      {groupFields.length > 0 ? (
        <dl className="grid gap-x-4 gap-y-1.5 border-t px-3.5 py-2.5 sm:grid-cols-2 md:grid-cols-3">
          {groupFields.map(([key, item]) => (
            <DetailField key={key} label={key} value={item} />
          ))}
        </dl>
      ) : null}
      <div className="divide-y border-t">
        {rows.map(({ itemIndex, outcome }) => {
          const item = group.items[itemIndex]
          if (!item) return null
          const singleEffect = outcome?.effects.length === 1 ? outcome.effects[0] : undefined
          const itemFields = visibleItemFields(group, item.fields)
          return (
            <div
              className="min-w-0 space-y-2 px-3.5 py-3"
              key={`${group.key}:${String(itemIndex)}`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground text-[11px] tabular-nums">
                  Item {itemIndex + 1}
                </span>
                {outcome ? <OutcomeBadge status={outcome.status} /> : null}
              </div>
              <dl className="grid gap-x-4 gap-y-1.5 sm:grid-cols-2 md:grid-cols-3">
                {itemFields.map(([key, value]) => (
                  <DetailField key={key} label={key} value={value} />
                ))}
                {outcome
                  ? Object.entries(outcome.fields).map(([key, value]) => (
                      <DetailField key={`outcome:${key}`} label={key} value={value} />
                    ))
                  : null}
              </dl>
              {singleEffect ? <SingleEffectSummary effect={singleEffect} /> : null}
              {outcome && outcome.effects.length > 1 ? (
                <div className="bg-muted/25 min-w-0 px-2.5 py-2">
                  <p className="text-muted-foreground mb-1.5 text-[11px] font-medium">
                    {outcome.effects.length} concrete effects
                  </p>
                  <StructuredRecordTable
                    records={outcome.effects.map((effect) => ({
                      status: effect.status,
                      ...effect.fields,
                      ...(effect.external_ref ? { external_ref: effect.external_ref } : {}),
                      ...(effect.error_code ? { error_code: effect.error_code } : {}),
                    }))}
                  />
                </div>
              ) : null}
            </div>
          )
        })}
      </div>
    </article>
  )
}

function SingleEffectSummary({ effect }: { effect: OperationOutcome["effects"][number] }) {
  if (!effect.external_ref && !effect.error_code) return null
  return (
    <p className="text-muted-foreground min-w-0 text-[11px]">
      <span className="font-medium">{effect.error_code ? "Error" : "Provider reference"}</span>{" "}
      <span className="font-mono break-all">{effect.error_code ?? effect.external_ref}</span>
    </p>
  )
}

function OutcomeBadge({ status }: { status: OperationOutcomeStatus }) {
  return <StatusBadge status={status} />
}

function StatusBadge({ count, status }: { count?: number; status: OperationOutcomeStatus }) {
  const variant =
    status === "applied"
      ? "success"
      : status === "failed"
        ? "destructive"
        : status === "unverified"
          ? "warning"
          : "secondary"
  return (
    <Badge variant={variant}>
      {count === undefined
        ? titleCaseToken(status, status)
        : `${String(count)} ${status === "applied" ? "Successful" : titleCaseToken(status, status)}`}
    </Badge>
  )
}

function DetailField({ label, value }: { label: string; value: AuditDetailValue | undefined }) {
  return (
    <div className={isStructuredRecordArray(value) ? "min-w-0 sm:col-span-2" : "min-w-0"}>
      <dt className="text-muted-foreground text-xs">{titleCaseToken(label, label)}</dt>
      <dd className="mt-0.5 text-sm wrap-break-word">
        <DetailValue field={label} value={value} />
      </dd>
    </div>
  )
}

function SectionLabel({ children }: { children: string }) {
  return <h3 className="text-muted-foreground text-xs font-medium">{children}</h3>
}

function DetailValue({ field, value }: { field: string; value: AuditDetailValue | undefined }) {
  if (field === "reason" && typeof value === "string") {
    return titleCaseToken(value, value)
  }
  return isStructuredRecordArray(value) ? (
    <StructuredRecordTable records={value} />
  ) : (
    formatDetailValue(value)
  )
}

function StructuredRecordTable({ records }: { records: Record<string, AuditDetailValue>[] }) {
  const [pageOffset, setPageOffset] = useState(0)
  const columns = useMemo(() => recordColumns(records), [records])
  const page = paginateItems(records, pageOffset, AUDIT_DETAIL_PAGE_SIZE)
  return (
    <TooltipProvider>
      <div className="space-y-2">
        <div className="overflow-x-auto">
          <table aria-label="Structured details" className="w-full min-w-max text-left text-sm">
            <thead>
              <tr className="border-b">
                {columns.map((key) => (
                  <th
                    className="text-muted-foreground pr-4 pb-2 text-[11px] font-medium last:pr-0"
                    key={key}
                    scope="col"
                  >
                    {titleCaseToken(key, key)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {page.items.map((record, index) => (
                <tr
                  className="border-b last:border-b-0"
                  key={detailRecordKey(record, page.offset + index)}
                >
                  {columns.map((key) => (
                    <td className="max-w-52 py-2 pr-4 align-top last:pr-0" key={key}>
                      <StructuredRecordValue field={key} value={record[key]} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {records.length > AUDIT_DETAIL_PAGE_SIZE ? (
          <PaginationControls
            ariaLabel="Structured details pagination"
            limit={AUDIT_DETAIL_PAGE_SIZE}
            offset={page.offset}
            onPageChange={setPageOffset}
            total={records.length}
          />
        ) : null}
      </div>
    </TooltipProvider>
  )
}

function StructuredRecordValue({
  field,
  value,
}: {
  field: string
  value: AuditDetailValue | undefined
}) {
  if (
    field === "status" &&
    (value === "applied" || value === "skipped" || value === "failed" || value === "unverified")
  ) {
    return <StatusBadge status={value} />
  }
  const formatted = formatDetailValue(value)
  if (formatted.length <= STRUCTURED_VALUE_PREVIEW_LENGTH) {
    return <span className="block max-w-full truncate">{formatted}</span>
  }
  return (
    <Tooltip>
      <TooltipTrigger className="block max-w-full truncate text-left" render={<span />}>
        {truncateText(formatted, STRUCTURED_VALUE_PREVIEW_LENGTH, "…")}
      </TooltipTrigger>
      <TooltipContent className="max-w-[min(48rem,calc(100vw-2rem))] break-all">
        {formatted}
      </TooltipContent>
    </Tooltip>
  )
}

function aggregateState(
  intents: OperationCounts,
  effects: OperationCounts
): "success" | "partial" | "failure" | "unverified" {
  if (intents.unverified > 0 || effects.unverified > 0) return "unverified"
  if (intents.failed === 0) return "success"
  return intents.failed === countTotal(intents) && effects.applied === 0 ? "failure" : "partial"
}

function countTotal(counts: OperationCounts): number {
  return counts.applied + counts.skipped + counts.failed + counts.unverified
}

function intentItemCount(detail: OperationDetail): number {
  return detail.intent_groups.reduce((total, group) => total + group.items.length, 0)
}

function visibleGroupFields(group: OperationIntentGroup): [string, AuditDetailValue][] {
  return Object.entries(group.fields).filter(([, value]) => {
    const comparable = typeof value === "string" ? value : null
    return comparable !== group.external_id && comparable !== group.display_name
  })
}

function visibleItemFields(
  group: OperationIntentGroup,
  fields: Record<string, AuditDetailValue>
): [string, AuditDetailValue][] {
  return Object.entries(fields).filter(([key, value]) => {
    if (group.fields[key] === value) return false
    return !(key.endsWith("_id") && value === group.external_id)
  })
}

function formatDetailValue(value: AuditDetailValue | undefined): string {
  if (value === undefined || value === null) return "None"
  if (typeof value === "boolean") return value ? "Yes" : "No"
  if (typeof value === "object") return JSON.stringify(value)
  return String(value)
}

function isDetailRecord(value: AuditDetailValue): value is Record<string, AuditDetailValue> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isStructuredRecordArray(
  value: AuditDetailValue | undefined
): value is Record<string, AuditDetailValue>[] {
  return Array.isArray(value) && value.length > 0 && value.every(isDetailRecord)
}

function recordColumns(records: Record<string, AuditDetailValue>[]): string[] {
  return [...new Set(records.flatMap((record) => Object.keys(record)))]
}

function detailRecordKey(record: Record<string, AuditDetailValue>, index: number): string {
  return `${String(index)}:${JSON.stringify(record)}`
}

function segmentIntentRows(rows: IntentItemRow[]): IntentItemSegment[] {
  const segments: IntentItemSegment[] = []
  for (const row of rows) {
    const current = segments.at(-1)
    if (current?.[0].groupIndex !== row.groupIndex) {
      segments.push([row])
    } else {
      current.push(row)
    }
  }
  return segments
}
