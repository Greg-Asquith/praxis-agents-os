// apps/web/src/integrations/meta_ads/components/create-ads.tsx

import { useId, useState } from "react"
import { CirclePauseIcon, CirclePlayIcon } from "lucide-react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { AdEditor } from "@/integrations/meta_ads/components/ad-editor"
import { AdsList } from "@/integrations/meta_ads/components/ads-list"
import { AutomaticChanges } from "@/integrations/meta_ads/components/automatic-changes"
import { SettingRows } from "@/integrations/meta_ads/components/setting-rows"
import { StatusChoice } from "@/integrations/meta_ads/components/status-choice"
import { UrlTagsRow } from "@/integrations/meta_ads/components/url-tags-row"
import { hasAiGeneratedChange } from "@/integrations/meta_ads/lib/automatic-changes"
import { clearAdStatuses, editSetting } from "@/integrations/meta_ads/lib/create-ads-edits"
import { MediaAccountContext } from "@/integrations/meta_ads/lib/meta-pictures"
import { MediaUploadOutcome } from "@/integrations/meta_ads/components/media-upload"
import {
  AdOutcomeLinks,
  MetaAdsOutcomeTable,
} from "@/integrations/meta_ads/components/outcome-table"
import { FORMAT_LABELS, type CreateAdsArgs } from "@/integrations/meta_ads/lib/create-ads-args"
import { adRows, statusLines, type AdRow } from "@/integrations/meta_ads/lib/create-ads-checks"
import { REVIEW_LABELS } from "@/integrations/meta_ads/lib/ad-outcome"
import { nextStep, type CreateAdsResult } from "@/integrations/meta_ads/lib/create-ads-result"
import { cn } from "@/lib/utils"

export function CreateAdsApproval({
  args,
  disabled,
  onFieldEdit,
}: {
  args: CreateAdsArgs
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const id = useId()
  const rows = adRows(args)
  // Opens the first ad that needs attention, so a problem is on screen before approving.
  const [selected, setSelected] = useState(() => firstToOpen(rows))
  const row = rows.find((item) => item.ad.index === selected) ?? rows[0]
  const aiOn = hasAiGeneratedChange(args.catalogue, args.enabledChanges)
  const delivery = statusLines(args, rows).join(" ")
  const count = rows.length
  const changeSetting = (key: "link" | "call_to_action" | "url_tags", value: string | null) => {
    if (!row) return
    const edit = editSetting(args, row.ad.index, key, value)
    onFieldEdit(edit.field, edit.value)
  }
  return (
    <MediaAccountContext value={args.accountId}>
      <div className="grid min-w-0 gap-4">
        <StatusChoice
          activeNote={delivery}
          disabled={disabled}
          label={count === 1 ? "Status for This Ad" : `Status for All ${String(count)} Ads`}
          lockedNote={
            aiOn
              ? "An AI-generated setting is on, so every ad is created paused. Check Meta's preview before turning them on."
              : null
          }
          onChange={(status) => {
            onFieldEdit("status", status)
            // Each ad follows the one status chosen here.
            const cleared = clearAdStatuses(args)
            if (cleared) onFieldEdit("ads", cleared)
          }}
          pausedNote={delivery}
          value={rows.some((item) => item.status === "active") ? "active" : "paused"}
        />
        {count > 1 ? (
          <AdsList args={args} onSelect={setSelected} rows={rows} selected={row?.ad.index ?? 0} />
        ) : null}
        {row ? (
          <section aria-label={`Edit ${row.ad.name || "ad"}`} className="min-w-0">
            <AdEditor
              key={row.ad.index}
              args={args}
              count={count}
              disabled={disabled}
              onEdit={(ads) => {
                onFieldEdit("ads", ads)
              }}
              onEditSetting={changeSetting}
              onSelect={setSelected}
              row={row}
            />
          </section>
        ) : null}
        <SettingRows ariaLabel="Settings for all ads">
          {row && !row.ad.post ? (
            <UrlTagsRow
              args={args}
              disabled={disabled}
              id={id}
              onEdit={(ads) => {
                onFieldEdit("ads", ads)
              }}
              onEditSetting={changeSetting}
              row={row}
            />
          ) : null}
          <AutomaticChanges
            args={args}
            disabled={disabled}
            onChange={(value) => {
              onFieldEdit("automatic_changes", value)
            }}
          />
        </SettingRows>
      </div>
    </MediaAccountContext>
  )
}

/** Says what approving means for delivery, highlighted when anything would start spending. */
export function DeliveryNote({ lines, runs }: { lines: readonly string[]; runs: boolean }) {
  return (
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
        <CirclePlayIcon aria-hidden="true" className="text-warning-text mt-0.5 size-4 shrink-0" />
      ) : (
        <CirclePauseIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      )}
      <ul className="grid gap-0.5">
        {lines.map((line) => (
          <li key={line} className="wrap-anywhere">
            {line}
          </li>
        ))}
      </ul>
    </div>
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
        renderCell={(column, row) =>
          column.key === "links" ? (
            <AdOutcomeLinks accountId={result.accountId} ad={result.ads[Number(row["index"])]} />
          ) : null
        }
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
