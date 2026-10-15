// apps/web/src/integrations/meta_ads/components/status-change.tsx

import { CheckIcon, PlusIcon, TriangleAlertIcon } from "lucide-react"
import { useState } from "react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { EntitySearch } from "@/integrations/meta_ads/components/entity-search"
import {
  MetaAdsLink,
  MetaAdsOutcomeTable,
  type MetaAdsOutcomeRow,
} from "@/integrations/meta_ads/components/outcome-table"
import { adsManagerObjectUrl } from "@/integrations/meta_ads/lib/ads-manager-link"
import {
  activationNotes,
  deliveryBlocked,
  deliveryLabel,
  OBJECT_TITLES,
  outcomeNote,
  startingSpend,
  statusLabel,
  statusListEdit,
  statusRows,
  STATUS_LISTS,
  targetKey,
  type MetaAdsRequestedStatus,
  type StatusChangeArgs,
  type StatusChangeResult,
  type StatusRow,
} from "@/integrations/meta_ads/lib/status-change"
import { formatCurrency } from "@/lib/format"
import { isRecord } from "@/lib/guards"
import { cn } from "@/lib/utils"

const CHANGES: readonly { value: MetaAdsRequestedStatus; label: string }[] = [
  { value: "ACTIVE", label: "Turn On" },
  { value: "PAUSED", label: "Pause" },
]
const TOOL_NAME = "meta_ads_update_status"

export function StatusApprovalSummary({
  args,
  disabled,
  onFieldEdit,
  onReview,
  proposed,
}: {
  args: StatusChangeArgs
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
  onReview?: (() => void) | undefined
  proposed: StatusChangeArgs
}) {
  const [adding, setAdding] = useState(false)
  const [addType, setAddType] = useState<(typeof STATUS_LISTS)[number]>(STATUS_LISTS[0])
  const rows = statusRows(proposed, args)
  const turningOn = args.status === "ACTIVE"
  const showEvidence = turningOn && !args.needsReview
  const kept = rows.filter((row) => row.included)
  const editList = (
    change: Parameters<typeof statusListEdit>[2],
    type: StatusRow["target"]["type"]
  ) => {
    const edit = statusListEdit(rows, type, change)
    onFieldEdit(edit.field, edit.value)
  }
  return (
    <div className="grid min-w-0 gap-3">
      <div
        aria-label="Change to"
        className="bg-muted/60 flex w-fit rounded-lg border p-0.5"
        role="radiogroup"
      >
        {CHANGES.map((change) => {
          const checked = change.value === args.status
          return (
            <button
              key={change.value}
              aria-checked={checked}
              className={cn(
                "focus-visible:ring-ring/50 h-8 min-w-24 cursor-pointer rounded-md px-3 text-sm font-medium outline-none focus-visible:ring-3 disabled:cursor-not-allowed disabled:opacity-60",
                checked && change.value === "ACTIVE" && "bg-primary text-primary-foreground",
                checked && change.value === "PAUSED" && "bg-foreground text-background",
                !checked && "text-foreground/70 hover:bg-muted"
              )}
              disabled={disabled}
              onClick={() => {
                if (!checked) onFieldEdit("status", change.value)
              }}
              role="radio"
              type="button"
            >
              {change.label}
            </button>
          )
        })}
      </div>
      {args.needsReview ? (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-muted-foreground text-sm">
            Check these changes to see what they turn on and spend.
          </p>
          <Button
            disabled={disabled || !onReview || kept.length === 0}
            onClick={onReview}
            type="button"
            variant="outline"
          >
            Check Changes
          </Button>
        </div>
      ) : null}
      {showEvidence ? <DeliveryStats args={args} rows={rows} /> : null}
      <ul
        aria-label="Proposed status changes"
        className="divide-y overflow-hidden rounded-lg border"
      >
        {rows.map((row) => (
          <li key={targetKey(row.target)} className="min-w-0 p-3">
            <StatusItem
              args={args}
              disabled={disabled}
              onToggle={(included) => {
                editList({ key: targetKey(row.target), included }, row.target.type)
              }}
              row={row}
              showEvidence={showEvidence}
            />
          </li>
        ))}
      </ul>
      {adding ? (
        <div className="grid gap-2 rounded-lg border p-3">
          <div aria-label="Add" className="flex flex-wrap gap-1" role="radiogroup">
            {STATUS_LISTS.map((list) => (
              <Button
                key={list.type}
                aria-checked={list.type === addType.type}
                disabled={disabled}
                onClick={() => {
                  setAddType(list)
                }}
                role="radio"
                type="button"
                variant={list.type === addType.type ? "secondary" : "ghost"}
              >
                {OBJECT_TITLES[list.type]}
              </Button>
            ))}
          </div>
          <EntitySearch
            key={addType.type}
            fieldKey={addType.key}
            isTaken={(choice) =>
              rows.some(
                (row) =>
                  row.target.type === addType.type &&
                  row.target.id === String(choice.value[addType.idKey])
              )
            }
            label={`Search ${OBJECT_TITLES[addType.type]}`}
            onChoose={(choice) => {
              editList({ added: choice.value }, addType.type)
              setAdding(false)
            }}
            toolName={TOOL_NAME}
          />
        </div>
      ) : null}
      <Button
        className="w-fit"
        disabled={disabled}
        onClick={() => {
          setAdding(!adding)
        }}
        type="button"
        variant="outline"
      >
        <PlusIcon />
        {adding ? "Cancel" : "Add a Campaign, Ad Set or Ad"}
      </Button>
    </div>
  )
}

function DeliveryStats({ args, rows }: { args: StatusChangeArgs; rows: StatusRow[] }) {
  const kept = rows.filter((row) => row.included)
  const blocked = kept.filter((row) => deliveryBlocked(row.target, args.delivery[row.target.id]))
  const spend = startingSpend(rows, args.delivery)
  const stats = [
    {
      label: "Starts Spending",
      value: spend
        ? `${spend.atLeast ? "At least " : "Up to "}${formatCurrency(spend.amount, spend.currency)} a day`
        : "Nothing yet",
    },
    {
      label: "Will Deliver",
      value: `${String(kept.length - blocked.length)} of ${String(kept.length)}`,
    },
    { label: "Needs Something Else On", value: String(blocked.length) },
  ]
  return (
    <dl
      className="border-warning/40 bg-warning/10 grid gap-3 rounded-lg border px-3 py-2.5 sm:grid-cols-3"
      role="note"
    >
      {stats.map((stat) => (
        <div key={stat.label} className="grid gap-0.5">
          <dt className="text-muted-foreground text-sm">{stat.label}</dt>
          <dd className="text-sm font-semibold tabular-nums">{stat.value}</dd>
        </div>
      ))}
    </dl>
  )
}

function StatusItem({
  args,
  disabled,
  onToggle,
  row,
  showEvidence,
}: {
  args: StatusChangeArgs
  disabled: boolean
  onToggle: (included: boolean) => void
  row: StatusRow
  showEvidence: boolean
}) {
  const { target, included } = row
  const impact = args.delivery[target.id]
  const delivery = deliveryLabel(target.status, target.effectiveStatus)
  const blocked = deliveryBlocked(target, impact)
  const href = adsManagerObjectUrl(target.type, target.accountId, target.id)
  return (
    <div className={cn("grid min-w-0 gap-1.5", !included && "opacity-60")}>
      <div className="flex min-w-0 items-start gap-3">
        <Checkbox
          aria-label={`Include ${target.name}`}
          checked={included}
          className="mt-0.5"
          disabled={disabled}
          onCheckedChange={onToggle}
        />
        <div className="grid min-w-0 flex-1 gap-0.5">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium wrap-anywhere">{target.name}</p>
            <Badge variant="secondary">{OBJECT_TITLES[target.type]}</Badge>
          </div>
          {target.scope ? <p className="text-muted-foreground text-sm">{target.scope}</p> : null}
        </div>
        <p className="shrink-0 text-sm whitespace-nowrap">
          <span className="text-muted-foreground">{statusLabel(target.status)}</span>
          {" → "}
          <span className="font-medium">{statusLabel(args.status)}</span>
        </p>
      </div>
      {delivery ? (
        <p className="text-muted-foreground pl-7 text-sm">Delivery now: {delivery}</p>
      ) : null}
      {included && showEvidence
        ? activationNotes(target, impact).map((note) => (
            <p
              key={note}
              className={cn(
                "flex items-start gap-2 pl-7 text-sm",
                blocked ? "text-warning-text" : "text-foreground/80"
              )}
            >
              {blocked ? (
                <TriangleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              ) : (
                <CheckIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              )}
              {note}
            </p>
          ))
        : null}
      {href ? (
        <div className="pl-7">
          <MetaAdsLink href={href}>Open in Ads Manager</MetaAdsLink>
        </div>
      ) : null}
    </div>
  )
}

export function StatusOutcome({ result }: { result: StatusChangeResult }) {
  const rows: (MetaAdsOutcomeRow & { delivery: string; href: string | null })[] =
    result.objects.map((object) => ({
      name: object.name,
      type: OBJECT_TITLES[object.type],
      before: statusLabel(object.previousStatus),
      after: object.outcome === "failed" ? "—" : statusLabel(object.status),
      delivery: deliveryLabel(object.status, object.effectiveStatus) ?? "",
      outcome: object.outcome,
      details: [object.message, outcomeNote(object)].filter(Boolean).join(" "),
      errorCode: object.errorCode,
      href: adsManagerObjectUrl(object.type, result.accountId, object.id),
    }))
  return (
    <MetaAdsOutcomeTable
      columns={[
        { key: "name", kind: "text", label: "Name" },
        { key: "type", kind: "text", label: "Type" },
        { key: "before", kind: "text", label: "Before" },
        { key: "after", kind: "text", label: "After" },
        ...(rows.some((row) => row.delivery)
          ? [{ key: "delivery", kind: "text" as const, label: "Delivery" }]
          : []),
      ]}
      rows={rows}
      exportFilename="meta-ads-status.csv"
      renderCell={(column, row) =>
        column.key === "name" && isRecord(row) && typeof row["href"] === "string" ? (
          <span className="grid gap-0.5">
            <span className="wrap-anywhere">{String(row["name"])}</span>
            <MetaAdsLink href={row["href"]}>Open in Ads Manager</MetaAdsLink>
          </span>
        ) : null
      }
    />
  )
}
