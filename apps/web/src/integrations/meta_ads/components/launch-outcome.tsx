// apps/web/src/integrations/meta_ads/components/launch-outcome.tsx

import { CircleAlertIcon, CircleCheckIcon, CirclePauseIcon } from "lucide-react"

import { MediaUploadOutcome } from "@/integrations/meta_ads/components/media-upload"
import {
  AdOutcomeLinks,
  MetaAdsLink,
  MetaAdsOutcomeTable,
  type MetaAdsOutcomeRow,
} from "@/integrations/meta_ads/components/outcome-table"
import { REVIEW_LABELS } from "@/integrations/meta_ads/lib/ad-outcome"
import type { OutcomeToken } from "@/integrations/meta_ads/lib/outcomes"
import { adsManagerObjectUrl } from "@/integrations/meta_ads/lib/ads-manager-link"
import { FORMAT_LABELS } from "@/integrations/meta_ads/lib/create-ads-args"
import { bannerTone, type LaunchResult } from "@/integrations/meta_ads/lib/launch-result"
import { cn } from "@/lib/utils"

const TURNED_ON = {
  turned_on: "On",
  not_turned_on: "Not Turned On",
  unverified: "Couldn't Confirm",
} as const
const LOST_REPLY = "Meta's reply was lost, so it was found by its name."
// Codes for an object the build never sent, because its parent wasn't created or the build stopped.
const NOT_SENT = new Set(["CAMPAIGN_NOT_CREATED", "AD_SET_NOT_CREATED", "NOT_DISPATCHED"])
const TONES = {
  good: { Icon: CircleCheckIcon, className: "" },
  neutral: { Icon: CirclePauseIcon, className: "" },
  warning: { Icon: CircleAlertIcon, className: "text-warning-text" },
} as const

/** One line for what the launch built and whether it is on, then every object it made. */
export function LaunchOutcome({ result }: { result: LaunchResult }) {
  const { Icon, className } = TONES[bannerTone(result.state)]
  return (
    <div className="grid min-w-0 gap-3">
      <p className={cn("flex min-w-0 items-start gap-2 text-sm", className)} role="status">
        <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <span className="min-w-0 wrap-anywhere">{result.message}</span>
      </p>
      {result.createdOffForAi ? (
        <p className="text-warning-text flex items-start gap-2 text-sm">
          <CircleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>
            An AI-generated setting is on, so the ads were created paused. Check Meta&apos;s preview
            before turning them on.
          </span>
        </p>
      ) : null}
      <MetaAdsOutcomeTable
        columns={[
          { key: "name", kind: "text", label: "Name" },
          { key: "type", kind: "text", label: "Type" },
          { key: "delivery", kind: "text", label: "Turned On" },
          { key: "review", kind: "text", label: "Meta Review" },
          { key: "links", kind: "text", label: "Links" },
        ]}
        exportFilename="meta-ads-launch.csv"
        renderCell={(column, row) => {
          if (column.key === "name") {
            return (
              <span className={cn("wrap-anywhere", row["level"] === "ad" && "pl-4")}>
                {String(row["name"])}
              </span>
            )
          }
          if (column.key !== "links") return null
          const ad = result.ads[Number(row["adIndex"])]
          if (row["level"] === "ad") {
            return ad?.adSetCreated ? <AdOutcomeLinks accountId={result.accountId} ad={ad} /> : null
          }
          const href =
            typeof row["id"] === "string" &&
            (row["level"] === "campaign" || row["level"] === "adset")
              ? adsManagerObjectUrl(row["level"], result.accountId, row["id"])
              : null
          return href ? <MetaAdsLink href={href}>Open in Ads Manager</MetaAdsLink> : null
        }}
        rows={launchRows(result)}
      />
      {result.uploads.length > 0 ? (
        <div className="grid gap-2">
          <p className="text-sm font-medium">Uploaded Images</p>
          <MediaUploadOutcome result={{ accountId: result.accountId, uploads: result.uploads }} />
        </div>
      ) : null}
    </div>
  )
}

/** The campaign, then each ad set followed by its ads. */
function launchRows(result: LaunchResult): MetaAdsOutcomeRow[] {
  const { campaign } = result
  const rows: MetaAdsOutcomeRow[] = [
    {
      level: "campaign",
      name: campaign.name,
      type: "Campaign",
      id: campaign.id,
      delivery: deliveryLabel(campaign.outcome, campaign.turnedOn),
      review: "",
      outcome: shownOutcome(campaign.outcome, campaign.errorCode),
      details: objectDetails(campaign),
      errorCode: campaign.errorCode,
    },
  ]
  for (const adSet of result.adSets) {
    rows.push({
      level: "adset",
      name: adSet.name,
      type: "Ad Set",
      id: adSet.id,
      delivery: deliveryLabel(adSet.outcome, adSet.turnedOn),
      review: "",
      outcome: shownOutcome(adSet.outcome, adSet.errorCode),
      details: objectDetails(adSet),
      errorCode: adSet.errorCode,
    })
    result.ads.forEach((ad, adIndex) => {
      if (ad.adSetKey !== adSet.key) return
      rows.push({
        level: "ad",
        adIndex,
        name: ad.name,
        type: `${FORMAT_LABELS[ad.format]} Ad`,
        id: ad.adId,
        delivery:
          ad.outcome === "created" ? (ad.requestedStatus === "active" ? "On" : "Paused") : "",
        review: ad.outcome === "created" ? REVIEW_LABELS[ad.review] : "",
        outcome: shownOutcome(ad.outcome, ad.errorCode),
        details: [
          ad.adSetCreated ? null : "Skipped: its ad set wasn't created.",
          ad.message,
          ad.recovered ? LOST_REPLY : null,
          ad.reviewReasons.length > 0 ? `Review: ${ad.reviewReasons.join(" ")}` : null,
        ]
          .filter(Boolean)
          .join(" "),
        errorCode: ad.errorCode,
      })
    })
  }
  return rows
}

function shownOutcome(outcome: OutcomeToken, errorCode: string | null): OutcomeToken {
  return outcome === "failed" && errorCode && NOT_SENT.has(errorCode) ? "skipped" : outcome
}

function deliveryLabel(outcome: string, turnedOn: keyof typeof TURNED_ON | null): string {
  if (outcome !== "created") return ""
  return turnedOn ? TURNED_ON[turnedOn] : "Paused"
}

function objectDetails(object: { message: string | null; recovered: boolean }): string {
  return [object.message, object.recovered ? LOST_REPLY : null].filter(Boolean).join(" ")
}
