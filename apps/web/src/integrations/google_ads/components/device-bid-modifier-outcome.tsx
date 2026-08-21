// apps/web/src/integrations/google_ads/components/device-bid-modifier-outcome.tsx

import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Stat, StatGroup } from "@/components/ui/stat"
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
  { key: "outcome", kind: "status", label: "Outcome" },
  { key: "strategy", kind: "text", label: "Bidding Strategy" },
  { key: "details", kind: "text", label: "Details" },
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
  const counts = outcomeCounts(result)
  const rows: DataRow[] = result.campaigns.flatMap((campaign) =>
    campaign.devices.map((device) => ({
      campaign: campaign.campaignName || campaign.campaignId,
      campaignId: campaign.campaignId,
      details: outcomeDetails(device),
      device: humanizeGoogleAdsToken(device.device),
      outcome:
        device.outcome === "already_set" ? "Already set" : humanizeGoogleAdsToken(device.outcome),
      previous:
        device.previousBidModifier === null
          ? "Not set"
          : formatDeviceBidAdjustment(device.previousBidModifier),
      requested: formatDeviceBidAdjustment(device.bidModifier),
      strategy: biddingStrategyLabel(campaign),
    }))
  )

  return (
    <DataTable
      columns={COLUMNS}
      exportFilename="device-bid-adjustments.csv"
      header={
        <StatGroup className="px-3 pt-2">
          <Stat
            label="Updated"
            tone={counts.updated > 0 ? "success" : undefined}
            value={counts.updated}
          />
          <Stat
            label="Already set"
            tone={counts.alreadySet > 0 ? "warning" : undefined}
            value={counts.alreadySet}
          />
          <Stat
            label="Failed"
            tone={counts.failed > 0 ? "danger" : undefined}
            value={counts.failed}
          />
        </StatGroup>
      }
      pageSize={25}
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

function outcomeCounts(result: DeviceBidModifierResult) {
  let alreadySet = 0
  let failed = 0
  let updated = 0
  for (const campaign of result.campaigns) {
    for (const device of campaign.devices) {
      if (device.outcome === "already_set") {
        alreadySet += 1
      } else if (device.outcome === "failed") {
        failed += 1
      } else {
        updated += 1
      }
    }
  }
  return { alreadySet, failed, updated }
}

function outcomeDetails(device: DeviceBidModifierOutcome): string {
  const details = [device.message, device.note]
  if (device.errorCode) {
    details.push(humanizeGoogleAdsToken(device.errorCode))
  }
  return details.filter((value): value is string => Boolean(value)).join(" · ") || "—"
}
