// apps/web/src/integrations/meta_ads/components/create-ads.tsx

import { useState } from "react"
import { CirclePauseIcon, CirclePlayIcon } from "lucide-react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { AdEditor } from "@/integrations/meta_ads/components/ad-editor"
import { AdsList } from "@/integrations/meta_ads/components/ads-list"
import { AutomaticChanges } from "@/integrations/meta_ads/components/automatic-changes"
import { MediaAccountContext } from "@/integrations/meta_ads/lib/meta-pictures"
import { MediaUploadOutcome } from "@/integrations/meta_ads/components/media-upload"
import { MetaAdsOutcomeTable } from "@/integrations/meta_ads/components/outcome-table"
import { adsManagerObjectUrl } from "@/integrations/meta_ads/lib/ads-manager-link"
import { FORMAT_LABELS, type CreateAdsArgs } from "@/integrations/meta_ads/lib/create-ads-args"
import {
  adRows,
  adSetDelivery,
  statusLines,
  type AdRow,
} from "@/integrations/meta_ads/lib/create-ads-checks"
import { nextStep, type CreateAdsResult } from "@/integrations/meta_ads/lib/create-ads-result"
import { cn } from "@/lib/utils"

const REVIEW_LABELS = {
  in_review: "In Review",
  approved: "Approved",
  rejected: "Rejected",
  with_issues: "Has Issues",
  unknown: "Not Shown Yet",
} as const

export function CreateAdsApproval({
  args,
  disabled,
  onFieldEdit,
}: {
  args: CreateAdsArgs
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const rows = adRows(args)
  // Opens the first ad that needs attention, so a problem is on screen before approving.
  const [selected, setSelected] = useState(() => firstToOpen(rows))
  const row = rows.find((item) => item.ad.index === selected) ?? rows[0]
  // True when any ad would start spending once Meta approves it.
  const runs = [...adSetDelivery(args, rows).values()].includes("runs")
  return (
    <MediaAccountContext value={args.accountId}>
      <div className="grid min-w-0 gap-4">
        <div
          className={cn(
            "flex items-start gap-2 text-sm",
            runs
              ? "border-warning/40 bg-warning/10 rounded-lg border px-3 py-2"
              : "text-muted-foreground"
          )}
          role="note"
        >
          {runs ? (
            <CirclePlayIcon
              aria-hidden="true"
              className="text-warning-foreground mt-0.5 size-4 shrink-0"
            />
          ) : (
            <CirclePauseIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          )}
          <ul className="grid gap-0.5">
            {statusLines(args, rows).map((line) => (
              <li key={line} className="wrap-anywhere">
                {line}
              </li>
            ))}
          </ul>
        </div>
        {rows.length > 1 ? (
          <AdsList args={args} onSelect={setSelected} rows={rows} selected={row?.ad.index ?? 0} />
        ) : null}
        {row ? (
          <section aria-label={`Edit ${row.ad.name || "ad"}`} className="min-w-0">
            <AdEditor
              key={row.ad.index}
              args={args}
              count={rows.length}
              disabled={disabled}
              onEdit={(ads) => {
                onFieldEdit("ads", ads)
              }}
              row={row}
            />
          </section>
        ) : null}
        <AutomaticChanges
          args={args}
          disabled={disabled}
          onChange={(value) => {
            onFieldEdit("automatic_changes", value)
          }}
        />
      </div>
    </MediaAccountContext>
  )
}

function firstToOpen(rows: readonly AdRow[]): number {
  const flagged =
    rows.find((row) => row.check === "error") ?? rows.find((row) => row.check === "warning")
  return (flagged ?? rows[0])?.ad.index ?? 0
}

export function CreateAdsOutcome({ result }: { result: CreateAdsResult }) {
  const step = nextStep(result)
  const rows = result.ads.map((ad, index) => ({
    index,
    name: ad.name,
    adSet: ad.adSetName ?? ad.adSetId,
    format: FORMAT_LABELS[ad.format],
    status: ad.requestedStatus === "active" ? "Active" : "Paused",
    review: ad.outcome === "created" ? REVIEW_LABELS[ad.review] : "",
    links: "",
    outcome: ad.outcome,
    details: [
      ad.message,
      ad.recovered ? "Meta's reply was lost, so the ad was found by its name." : null,
      ad.reviewReasons.length > 0 ? `Review: ${ad.reviewReasons.join(" ")}` : null,
    ]
      .filter(Boolean)
      .join(" "),
    errorCode: ad.errorCode,
  }))
  return (
    <div className="grid gap-3">
      {result.createdOffForAi ? (
        <p className="text-sm">
          These ads were created paused because an AI enhancement is on. Preview them on Meta before
          turning them on.
        </p>
      ) : null}
      <MetaAdsOutcomeTable
        columns={[
          { key: "name", kind: "text", label: "Ad" },
          { key: "adSet", kind: "text", label: "Ad Set" },
          { key: "format", kind: "text", label: "Format" },
          { key: "status", kind: "text", label: "Status" },
          { key: "review", kind: "text", label: "Meta Review" },
          { key: "links", kind: "text", label: "Links" },
        ]}
        exportFilename="meta-ads-created-ads.csv"
        renderCell={(column, row) => {
          const ad = column.key === "links" ? result.ads[Number(row["index"])] : undefined
          if (!ad?.adId) return null
          const manager = adsManagerObjectUrl("ad", result.accountId, ad.adId)
          return (
            <span className="flex flex-col gap-0.5">
              {ad.previewUrl ? (
                <OutcomeLink href={ad.previewUrl}>Preview on Meta</OutcomeLink>
              ) : null}
              {manager ? <OutcomeLink href={manager}>Open in Ads Manager</OutcomeLink> : null}
            </span>
          )
        }}
        rows={rows}
      />
      {result.uploads.length > 0 ? (
        <div className="grid gap-2">
          <p className="text-sm font-medium">Uploaded Images</p>
          <MediaUploadOutcome result={{ accountId: result.accountId, uploads: result.uploads }} />
        </div>
      ) : null}
      {step ? <p className="text-sm">{step}</p> : null}
    </div>
  )
}

function OutcomeLink({ href, children }: { href: string; children: string }) {
  return (
    <a
      className="text-primary w-fit text-xs underline-offset-2 hover:underline"
      href={href}
      rel="noreferrer"
      target="_blank"
    >
      {children}
    </a>
  )
}
