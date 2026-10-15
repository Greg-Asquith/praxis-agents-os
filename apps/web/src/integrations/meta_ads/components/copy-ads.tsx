// apps/web/src/integrations/meta_ads/components/copy-ads.tsx

import { PlusIcon } from "lucide-react"
import { useId, useState } from "react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { DeliveryNote } from "@/integrations/meta_ads/components/create-ads"
import { EntitySearch } from "@/integrations/meta_ads/components/entity-search"
import { MediaFrame } from "@/integrations/meta_ads/components/media-frame"
import {
  AdOutcomeLinks,
  MetaAdsOutcomeTable,
} from "@/integrations/meta_ads/components/outcome-table"
import { SettingRow, SettingRows } from "@/integrations/meta_ads/components/setting-rows"
import { StatusChoice } from "@/integrations/meta_ads/components/status-choice"
import {
  copyNextStep,
  copyRows,
  editCopy,
  sourceName,
  type CopyAdsArgs,
  type CopyAdsResult,
  type CopyDraft,
} from "@/integrations/meta_ads/lib/copy-ads"
import { adSetName, FORMAT_LABELS } from "@/integrations/meta_ads/lib/create-ads-args"
import { adSetDelivery, statusLines } from "@/integrations/meta_ads/lib/create-ads-checks"
import { REVIEW_LABELS } from "@/integrations/meta_ads/lib/ad-outcome"
import { MediaAccountContext } from "@/integrations/meta_ads/lib/meta-pictures"

const TOOL_NAME = "meta_ads_copy_ads"

export function CopyAdsApproval({
  args,
  disabled,
  onFieldEdit,
}: {
  args: CopyAdsArgs
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const rows = copyRows(args)
  const runs = [...adSetDelivery(args, rows).values()].includes("runs")
  return (
    <MediaAccountContext value={args.accountId}>
      <div className="grid min-w-0 gap-3">
        <p className="text-muted-foreground text-sm">
          Copies are paused by default. Open a copy to set it to Active before it&apos;s created.
          Each copy keeps its source ad&apos;s picture, text, link, and automatic changes.
        </p>
        <DeliveryNote lines={statusLines(args, rows)} runs={runs} />
        <SettingRows ariaLabel="Ads to copy">
          {args.copies.map((copy) => (
            <SettingRow
              key={copy.index}
              rowKey={String(copy.index)}
              summary={`→ ${adSetName(args, copy.adSetId)} · ${copy.source?.aiGenerated || copy.status === "paused" ? "Paused" : "Active"}`}
              title={sourceName(copy)}
              tone={copy.status === "active" && !copy.source?.aiGenerated ? "warning" : "neutral"}
            >
              <CopyItem
                args={args}
                copy={copy}
                disabled={disabled}
                onEdit={(edit) => {
                  onFieldEdit("copies", editCopy(args, copy.index, edit))
                }}
              />
            </SettingRow>
          ))}
        </SettingRows>
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
  onEdit: (edit: Parameters<typeof editCopy>[2]) => void
}) {
  const id = useId()
  const [picking, setPicking] = useState<"change" | "add" | null>(null)
  const source = copy.source
  const changes = source?.automaticChanges ?? []
  const taken = (adSetId: string) =>
    adSetId === copy.sourceAdSetId ||
    args.copies.some((other) => other.adId === copy.adId && other.adSetId === adSetId)
  const pick = (mode: "change" | "add") => {
    setPicking(picking === mode ? null : mode)
  }
  return (
    <div className="grid min-w-0 gap-3">
      <div className="flex min-w-0 items-start gap-3">
        <MediaFrame
          className="size-14 shrink-0 rounded-md"
          media={source?.media ?? null}
          shape="square"
        />
        <div className="grid min-w-0 flex-1 gap-0.5 text-sm">
          {source?.excerpt ? (
            <p className="line-clamp-3 wrap-anywhere">&ldquo;{source.excerpt}&rdquo;</p>
          ) : null}
          <p className="text-muted-foreground">
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
      <div className="grid gap-1">
        <label className="text-sm font-medium" htmlFor={`${id}-name`}>
          New Name
        </label>
        <Input
          disabled={disabled}
          id={`${id}-name`}
          onChange={(event) => {
            onEdit({ name: event.currentTarget.value })
          }}
          placeholder={sourceName(copy)}
          value={copy.name ?? ""}
        />
      </div>
      <div className="grid gap-1">
        <span className="text-sm font-medium">Into Ad Set</span>
        <div className="flex flex-wrap items-center gap-2">
          <span className="min-w-0 text-sm wrap-anywhere">{adSetName(args, copy.adSetId)}</span>
          <Button
            disabled={disabled}
            onClick={() => {
              pick("change")
            }}
            type="button"
            variant="outline"
          >
            {picking === "change" ? "Cancel" : "Change"}
          </Button>
        </div>
        {picking === "change" ? (
          <EntitySearch
            entityKind="meta_ads_ad_set"
            fieldKey="copies"
            isTaken={(choice) => taken(String(choice.value["adset_id"]))}
            label="Search ad sets"
            onChoose={(choice) => {
              onEdit({ adSet: choice.value })
              setPicking(null)
            }}
            toolName={TOOL_NAME}
          />
        ) : null}
      </div>
      <StatusChoice
        activeNote="Starts running once Meta approves it, and spends from the ad set's budget."
        disabled={disabled}
        label="Status"
        lockedNote={source?.aiGenerated ? "Paused because an AI enhancement is on." : null}
        onChange={(status) => {
          onEdit({ status })
        }}
        pausedNote="Created paused. Nothing runs or spends until you turn it on."
        value={source?.aiGenerated ? "paused" : copy.status}
      />
      {picking === "add" ? (
        <EntitySearch
          entityKind="meta_ads_ad_set"
          fieldKey="copies"
          isTaken={(choice) => taken(String(choice.value["adset_id"]))}
          label="Search ad sets for another copy"
          onChoose={(choice) => {
            onEdit({ copyInto: choice.value })
            setPicking(null)
          }}
          toolName={TOOL_NAME}
        />
      ) : null}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button
          disabled={disabled}
          onClick={() => {
            pick("add")
          }}
          type="button"
          variant="outline"
        >
          <PlusIcon />
          {picking === "add" ? "Cancel" : "Copy Into Another Ad Set"}
        </Button>
        <Button
          aria-label={`Remove the copy of ${sourceName(copy)} into ${adSetName(args, copy.adSetId)}`}
          disabled={disabled}
          onClick={() => {
            onEdit({ remove: true })
          }}
          type="button"
          variant="ghost"
        >
          Remove
        </Button>
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
        renderCell={(column, row) =>
          column.key === "links" ? (
            <AdOutcomeLinks accountId={result.accountId} ad={result.copies[Number(row["index"])]} />
          ) : null
        }
        rows={rows}
      />
      {step ? <p className="text-sm">{step}</p> : null}
    </div>
  )
}
