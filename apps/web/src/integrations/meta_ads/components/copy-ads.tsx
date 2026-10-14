// apps/web/src/integrations/meta_ads/components/copy-ads.tsx

import { useState } from "react"
import { ArrowRightIcon } from "lucide-react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { PaginationControls, paginateItems } from "@/components/ui/pagination-controls"
import { DeliveryNote, OutcomeLink } from "@/integrations/meta_ads/components/create-ads"
import { LabelledInput, LabelledSelect } from "@/integrations/meta_ads/components/editor-fields"
import { MediaFrame } from "@/integrations/meta_ads/components/media-frame"
import { MetaAdsOutcomeTable } from "@/integrations/meta_ads/components/outcome-table"
import { adsManagerObjectUrl } from "@/integrations/meta_ads/lib/ads-manager-link"
import {
  copyNextStep,
  copyRows,
  editCopy,
  sourceName,
  type CopyAdsArgs,
  type CopyAdsResult,
  type CopyDraft,
} from "@/integrations/meta_ads/lib/copy-ads"
import {
  adSetName,
  FORMAT_LABELS,
  STATUS_OPTIONS,
} from "@/integrations/meta_ads/lib/create-ads-args"
import { adSetDelivery, statusLines } from "@/integrations/meta_ads/lib/create-ads-checks"
import { REVIEW_LABELS } from "@/integrations/meta_ads/lib/create-ads-result"
import { MediaAccountContext } from "@/integrations/meta_ads/lib/meta-pictures"

const PAGE_SIZE = 10

export function CopyAdsApproval({
  args,
  disabled,
  onFieldEdit,
}: {
  args: CopyAdsArgs
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const [offset, setOffset] = useState(0)
  const rows = copyRows(args)
  const runs = [...adSetDelivery(args, rows).values()].includes("runs")
  const page = paginateItems(args.copies, offset, PAGE_SIZE)
  return (
    <MediaAccountContext value={args.accountId}>
      <div className="grid min-w-0 gap-4">
        <DeliveryNote lines={statusLines(args, rows)} runs={runs} />
        <p className="text-muted-foreground text-sm">
          Each copy keeps its source ad&apos;s picture, text, link, and automatic changes.
        </p>
        <ul aria-label="Ads to copy" className="divide-y overflow-hidden rounded-lg border">
          {page.items.map((copy) => (
            <li key={copy.index} className="min-w-0 p-3">
              <CopyItem
                args={args}
                copy={copy}
                disabled={disabled}
                onEdit={(key, value) => {
                  onFieldEdit("copies", editCopy(args, copy.index, key, value))
                }}
              />
            </li>
          ))}
        </ul>
        {args.copies.length > PAGE_SIZE ? (
          <PaginationControls
            ariaLabel="Copies pages"
            limit={PAGE_SIZE}
            offset={page.offset}
            onPageChange={setOffset}
            total={args.copies.length}
          />
        ) : null}
      </div>
    </MediaAccountContext>
  )
}

function CopyItem({
  args,
  copy,
  disabled,
  onEdit,
}: {
  args: CopyAdsArgs
  copy: CopyDraft
  disabled: boolean
  onEdit: (key: "name" | "status", value: string) => void
}) {
  const source = copy.source
  const id = `meta-ads-copy-${String(copy.index)}`
  const changes = source?.automaticChanges ?? []
  return (
    <div className="grid min-w-0 gap-3">
      <div className="flex min-w-0 items-start gap-3">
        <MediaFrame
          className="size-14 shrink-0 rounded-md"
          media={source?.media ?? null}
          shape="square"
        />
        <div className="grid min-w-0 flex-1 gap-0.5">
          <p className="flex min-w-0 flex-wrap items-center gap-1 text-sm font-medium">
            <span className="wrap-anywhere">{sourceName(copy)}</span>
            <ArrowRightIcon aria-label="into" className="text-muted-foreground size-3.5" />
            <span className="wrap-anywhere">{adSetName(args, copy.adSetId)}</span>
          </p>
          {source?.excerpt ? (
            <p className="text-muted-foreground line-clamp-2 text-xs wrap-anywhere">
              {source.excerpt}
            </p>
          ) : null}
          <p className="text-muted-foreground text-xs">
            {[
              source?.format ? FORMAT_LABELS[source.format] : null,
              changes.length > 0
                ? `Automatic changes on: ${changes.join(", ")}`
                : "No automatic changes on",
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
      </div>
      <div className="grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_10rem]">
        <LabelledInput
          disabled={disabled}
          id={`${id}-name`}
          label="Name"
          onChange={(value) => {
            onEdit("name", value)
          }}
          placeholder={sourceName(copy)}
          value={copy.name ?? ""}
        />
        <LabelledSelect
          disabled={disabled || Boolean(source?.aiGenerated)}
          id={`${id}-status`}
          label="Status"
          note={source?.aiGenerated ? "Paused because an AI enhancement is on." : null}
          onChange={(value) => {
            onEdit("status", value)
          }}
          options={STATUS_OPTIONS}
          value={source?.aiGenerated ? "paused" : copy.status}
        />
      </div>
    </div>
  )
}

export function CopyAdsOutcome({ result }: { result: CopyAdsResult }) {
  const step = copyNextStep(result)
  const rows = result.copies.map((copy, index) => ({
    index,
    name: copy.name,
    source: copy.sourceName ?? "",
    adSet: copy.adSetName ?? copy.adSetId,
    status: copy.requestedStatus === "active" ? "Active" : "Paused",
    review: copy.outcome === "copied" ? REVIEW_LABELS[copy.review] : "",
    links: "",
    outcome: copy.outcome,
    details: [
      copy.message,
      copy.recovered ? "Meta's reply was lost, so the copy was found by its name." : null,
      copy.pausedForAi ? "Copied paused because an AI enhancement is on." : null,
      copy.reviewReasons.length > 0 ? `Review: ${copy.reviewReasons.join(" ")}` : null,
    ]
      .filter(Boolean)
      .join(" "),
    errorCode: copy.errorCode,
  }))
  return (
    <div className="grid gap-3">
      <MetaAdsOutcomeTable
        columns={[
          { key: "name", kind: "text", label: "Ad" },
          { key: "source", kind: "text", label: "Copied From" },
          { key: "adSet", kind: "text", label: "Ad Set" },
          { key: "status", kind: "text", label: "Status" },
          { key: "review", kind: "text", label: "Meta Review" },
          { key: "links", kind: "text", label: "Links" },
        ]}
        exportFilename="meta-ads-copied-ads.csv"
        renderCell={(column, row) => {
          const copy = column.key === "links" ? result.copies[Number(row["index"])] : undefined
          if (!copy?.adId) return null
          const manager = adsManagerObjectUrl("ad", result.accountId, copy.adId)
          return (
            <span className="flex flex-col gap-0.5">
              {copy.previewUrl ? (
                <OutcomeLink href={copy.previewUrl}>Preview on Meta</OutcomeLink>
              ) : null}
              {manager ? <OutcomeLink href={manager}>Open in Ads Manager</OutcomeLink> : null}
            </span>
          )
        }}
        rows={rows}
      />
      {step ? <p className="text-sm">{step}</p> : null}
    </div>
  )
}
