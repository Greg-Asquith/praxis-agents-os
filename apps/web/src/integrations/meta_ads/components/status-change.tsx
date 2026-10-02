// apps/web/src/integrations/meta_ads/components/status-change.tsx

import { Button } from "@/components/ui/button"
import { MetaAdsApprovalSection } from "@/integrations/meta_ads/components/approval-section"
import {
  MetaAdsManagerLink,
  MetaAdsObjectCard,
} from "@/integrations/meta_ads/components/object-card"
import {
  MetaAdsOutcomeTable,
  type MetaAdsOutcomeRow,
} from "@/integrations/meta_ads/components/outcome-table"
import { adsManagerObjectUrl } from "@/integrations/meta_ads/lib/ads-manager-link"
import {
  activationNotes,
  deliveryLabel,
  OBJECT_TITLES,
  outcomeNote,
  requestedStatusLabel,
  statusLabel,
  targetCounts,
  type StatusChangeArgs,
  type StatusChangeResult,
  type StatusTarget,
} from "@/integrations/meta_ads/lib/status-change"
import { isRecord } from "@/lib/guards"

export function StatusApprovalSummary({
  args,
  disabled = false,
  onReview,
}: {
  args: StatusChangeArgs
  disabled?: boolean
  onReview?: (() => void) | undefined
}) {
  return (
    <div className="grid gap-3">
      {args.needsReview ? (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-muted-foreground text-sm">
            Check these changes to see what they turn on and spend.
          </p>
          <Button
            disabled={disabled || !onReview}
            onClick={onReview}
            size="sm"
            type="button"
            variant="outline"
          >
            Check Changes
          </Button>
        </div>
      ) : null}
      <StatusTargets args={args} />
    </div>
  )
}

function StatusTargets({ args }: { args: StatusChangeArgs }) {
  const turningOn = args.status === "ACTIVE"
  return (
    <MetaAdsApprovalSection
      ariaLabel="Proposed status changes"
      tone={turningOn ? "spend" : "neutral"}
      warning={turningOn ? "Turning on spends money." : null}
      countLine={`${requestedStatusLabel(args.status)}: ${targetCounts(args.targets)}`}
    >
      {args.targets.map((target) => (
        <MetaAdsObjectCard
          key={`${target.type}:${target.id}`}
          title={target.name}
          typeLabel={OBJECT_TITLES[target.type]}
          meta={targetMeta(target)}
          notes={
            turningOn && !args.needsReview ? activationNotes(target, args.delivery[target.id]) : []
          }
          href={adsManagerObjectUrl(target.type, target.accountId, target.id)}
        />
      ))}
    </MetaAdsApprovalSection>
  )
}

function targetMeta(target: StatusTarget): string {
  const delivery = deliveryLabel(target.status, target.effectiveStatus)
  const now = target.status
    ? `Now ${statusLabel(target.status)}${delivery ? ` (${delivery})` : ""}`
    : null
  return [target.scope, now].filter(Boolean).join(" · ")
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
            <MetaAdsManagerLink href={row["href"]} />
          </span>
        ) : null
      }
    />
  )
}
