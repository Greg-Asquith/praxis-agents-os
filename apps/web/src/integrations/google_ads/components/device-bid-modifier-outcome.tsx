// apps/web/src/integrations/google_ads/components/device-bid-modifier-outcome.tsx

import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"
import type { DataColumn } from "@/components/ui/data-table"
import { GoogleAdsApprovalSection } from "@/integrations/google_ads/components/approval-section"
import { GoogleAdsEntityCard } from "@/integrations/google_ads/components/entity-card"
import {
  GoogleAdsOutcomeTable,
  type GoogleAdsOutcomeRow,
} from "@/integrations/google_ads/components/outcome-table"
import { formatBidAdjustment } from "@/integrations/google_ads/lib/bid-modifiers"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { countByKind, outcomeDetails } from "@/integrations/google_ads/lib/outcomes"

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
    <GoogleAdsApprovalSection
      ariaLabel="Proposed device bid adjustments"
      countLine={approvalCountLine(campaignCount, "campaign")}
    >
      <div className="grid gap-1.5 sm:grid-cols-3">
        {adjustments.map((adjustment) => (
          <GoogleAdsEntityCard
            key={adjustment.device}
            title={googleAdsTokenLabel(adjustment.device)}
            trailing={formatBidAdjustment(adjustment.bidModifier)}
          />
        ))}
      </div>
    </GoogleAdsApprovalSection>
  )
}

export function DeviceBidModifierOutcomeCard({ result }: { result: DeviceBidModifierResult }) {
  const rows: GoogleAdsOutcomeRow[] = result.campaigns.flatMap((campaign) =>
    campaign.devices.map((device) => ({
      campaign: campaign.campaignName || campaign.campaignId,
      campaignId: campaign.campaignId,
      details: outcomeDetails(device.message, null, device.note),
      errorCode: device.errorCode,
      device: googleAdsTokenLabel(device.device),
      outcome: device.outcome,
      previous:
        device.previousBidModifier === null
          ? "Not set"
          : formatBidAdjustment(device.previousBidModifier),
      requested: formatBidAdjustment(device.bidModifier),
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
  const strategy = googleAdsTokenLabel(campaign.biddingStrategyType)
  return campaign.biddingStrategyType === "MAXIMIZE_CONVERSIONS" && campaign.targetCpaConfigured
    ? `${strategy} · Target CPA`
    : strategy
}
