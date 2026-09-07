// apps/web/src/integrations/google_ads/presenters/device-bid-modifiers.tsx

import {
  DeviceBidModifierApprovalSummary,
  DeviceBidModifierOutcomeCard,
  type DeviceBidModifierCampaign,
  type DeviceBidModifierOutcome,
  type DeviceBidModifierResult,
} from "@/integrations/google_ads/components/device-bid-modifier-outcome"
import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import { formatBidAdjustment } from "@/integrations/google_ads/lib/bid-modifiers"
import { googleAdsWriteCopy } from "@/integrations/google_ads/lib/copy"
import {
  deviceBidModifierArgs,
  deviceBidModifierArgsError,
  DEVICES,
  type DeviceBidModifierArgs,
} from "@/integrations/google_ads/lib/device-bid-modifier-inputs"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"
import { isNullableFiniteNumber, isNullableString, isOneOf, isRecord } from "@/lib/guards"
const OUTCOMES = new Set(["updated", "already_set", "failed"] as const)

const copy = googleAdsWriteCopy({
  verb: "Update",
  object: "device bid adjustments",
  effect: "updated",
})

export const googleAdsDeviceBidModifiersPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-update-device-bid-modifiers",
  variants: {
    google_ads_update_device_bid_modifiers: defineGoogleAdsWriteVariant({
      ...copy,
      approval: {
        ...copy.approval,
        parseArgs: deviceBidModifierArgs,
        prompt:
          "Review the campaigns and multipliers before changing how much these campaigns bid per device.",
        renderSummary: (value, fallback) => {
          const args = deviceBidModifierArgs(value) ?? fallback
          return (
            <DeviceBidModifierApprovalSummary
              adjustments={args.adjustments}
              campaignCount={args.campaignIds.length}
            />
          )
        },
        validateArgs: deviceBidModifierArgsError,
      },
      details: deviceBidModifierDetails,
      parseResult: deviceBidModifierResult,
      renderFailure: (args, description) => (
        <GoogleAdsFailureTargets targets={args?.campaignLabels ?? []} description={description} />
      ),
      renderOutcome: (result) => <DeviceBidModifierOutcomeCard result={result} />,
    }),
  },
})

function deviceBidModifierDetails(args: DeviceBidModifierArgs | null) {
  if (!args) {
    return []
  }
  return [
    { label: "Campaigns", value: args.campaignLabels.join(", ") },
    {
      label: "Adjustments",
      value: args.adjustments
        .map((item) => `${item.device}: ${formatBidAdjustment(item.bidModifier)}`)
        .join(", "),
    },
  ]
}

function deviceBidModifierResult(value: unknown): DeviceBidModifierResult | null {
  if (!isRecord(value) || !Array.isArray(value["campaigns"]) || value["campaigns"].length === 0) {
    return null
  }
  const campaigns: DeviceBidModifierCampaign[] = []
  const campaignIds = new Set<string>()
  for (const item of value["campaigns"]) {
    if (
      !isRecord(item) ||
      typeof item["campaign_id"] !== "string" ||
      typeof item["campaign_name"] !== "string" ||
      typeof item["bidding_strategy_type"] !== "string" ||
      typeof item["target_cpa_configured"] !== "boolean" ||
      !Array.isArray(item["devices"]) ||
      item["devices"].length === 0 ||
      campaignIds.has(item["campaign_id"])
    ) {
      return null
    }
    campaignIds.add(item["campaign_id"])
    const devices: DeviceBidModifierOutcome[] = []
    const deviceNames = new Set<DeviceBidModifierOutcome["device"]>()
    for (const device of item["devices"]) {
      const parsed = deviceOutcome(device)
      if (!parsed || deviceNames.has(parsed.device)) {
        return null
      }
      deviceNames.add(parsed.device)
      devices.push(parsed)
    }
    campaigns.push({
      biddingStrategyType: item["bidding_strategy_type"],
      campaignId: item["campaign_id"],
      campaignName: item["campaign_name"] || item["campaign_id"],
      devices,
      targetCpaConfigured: item["target_cpa_configured"],
    })
  }
  return { campaigns }
}

function deviceOutcome(value: unknown): DeviceBidModifierOutcome | null {
  if (
    !isRecord(value) ||
    !isOneOf(DEVICES, value["device"]) ||
    typeof value["requested_bid_modifier"] !== "number" ||
    !Number.isFinite(value["requested_bid_modifier"]) ||
    !isOneOf(OUTCOMES, value["outcome"])
  ) {
    return null
  }
  const previous = value["previous_bid_modifier"] ?? null
  if (!isNullableFiniteNumber(previous)) {
    return null
  }
  const externalRef = value["external_ref"] ?? null
  const message = value["message"] ?? null
  const errorCode = value["error_code"] ?? null
  const note = value["note"] ?? null
  if (
    !isNullableString(externalRef) ||
    !isNullableString(message) ||
    !isNullableString(errorCode) ||
    !isNullableString(note) ||
    (value["outcome"] !== "failed" && !externalRef)
  ) {
    return null
  }
  return {
    bidModifier: value["requested_bid_modifier"],
    device: value["device"],
    errorCode,
    externalRef,
    message,
    note,
    outcome: value["outcome"],
    previousBidModifier: previous,
  }
}
