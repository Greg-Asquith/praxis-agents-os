// apps/web/src/integrations/google_ads/components/device-bid-modifier-outcome.tsx

import type { DataColumn } from "@/components/ui/data-table"
import {
  GoogleAdsOutcomeTable,
  type GoogleAdsOutcomeRow,
} from "@/integrations/google_ads/components/outcome-table"
import { countByKind, outcomeDetails } from "@/integrations/google_ads/lib/outcomes"
import {
  formatDeviceBidAdjustment,
  humanizeGoogleAdsToken,
} from "@/integrations/google_ads/lib/device-bid-modifiers"

export type DeviceAdjustment = {
  bidModifier: number
  device: "DESKTOP" | "MOBILE" | "TABLET"
}

export type DeviceBidModifierOutcome = DeviceAdjustment & {
  errorCode: string | null
  externalRef: string | null
  message: string | null
  note: string | null
  outcome: "already_set" | "failed" | "updated"
  previousBidModifier: number | null
}

export type DeviceBidModifierCampaign = {
  biddingStrategyType: string
  campaignId: string
  campaignName: string
  devices: DeviceBidModifierOutcome[]
  targetCpaConfigured: boolean
}

export type DeviceBidModifierResult = {
  campaigns: DeviceBidModifierCampaign[]
}

const COLUMNS: DataColumn[] = [
  { key: "campaign", kind: "text", label: "Campaign" },
  { key: "campaignId", kind: "id", label: "Campaign ID" },
  { key: "device", kind: "text", label: "Device" },
  { key: "previous", kind: "text", label: "Previous" },
  { key: "requested", kind: "text", label: "Requested" },
  { key: "strategy", kind: "text", label: "Bidding Strategy" },
]
export function DeviceBidModifierApprovalSummary({
  adjustments,
  campaignCount,
}: {
  adjustments: DeviceAdjustment[]
  campaignCount: number
}) {
  return (
    <section
      aria-label="Proposed device bid adjustments"
      className="border-border bg-muted/35 grid gap-2 rounded-lg border px-3 py-2.5"
    >
      <p className="text-muted-foreground text-xs">
        Applies to {String(campaignCount)} {campaignCount === 1 ? "campaign" : "campaigns"}
      </p>
      <dl className="grid gap-1.5 sm:grid-cols-3">
        {adjustments.map((adjustment) => (
          <div className="bg-card min-w-0 rounded-md border px-2.5 py-2" key={adjustment.device}>
            <dt className="text-muted-foreground text-xs">
              {humanizeGoogleAdsToken(adjustment.device)}
            </dt>
            <dd className="mt-0.5 text-sm font-medium tabular-nums">
              {formatDeviceBidAdjustment(adjustment.bidModifier)}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

export function DeviceBidModifierOutcomeCard({ result }: { result: DeviceBidModifierResult }) {
  const rows: GoogleAdsOutcomeRow[] = result.campaigns.flatMap((campaign) =>
    campaign.devices.map((device) => ({
      campaign: campaign.campaignName || campaign.campaignId,
      campaignId: campaign.campaignId,
      details: outcomeDetails(device.message, null, device.note),
      errorCode: device.errorCode,
      device: humanizeGoogleAdsToken(device.device),
      outcome: device.outcome,
      previous:
        device.previousBidModifier === null
          ? "Not set"
          : formatDeviceBidAdjustment(device.previousBidModifier),
      requested: formatDeviceBidAdjustment(device.bidModifier),
      strategy: biddingStrategyLabel(campaign),
    }))
  )

  return (
    <GoogleAdsOutcomeTable
      columns={COLUMNS}
      exportFilename="device-bid-adjustments.csv"
      outcomes={countByKind(rows)}
      rows={rows}
    />
  )
}

function biddingStrategyLabel(campaign: DeviceBidModifierCampaign): string {
  const strategy = humanizeGoogleAdsToken(campaign.biddingStrategyType)
  return campaign.biddingStrategyType === "MAXIMIZE_CONVERSIONS" && campaign.targetCpaConfigured
    ? `${strategy} · Target CPA`
    : strategy
}
