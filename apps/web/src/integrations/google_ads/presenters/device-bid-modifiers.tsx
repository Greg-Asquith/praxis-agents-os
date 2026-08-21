// apps/web/src/integrations/google_ads/presenters/device-bid-modifiers.tsx

import {
  DeviceBidModifierApprovalSummary,
  DeviceBidModifierOutcomeCard,
  type DeviceAdjustment,
  type DeviceBidModifierCampaign,
  type DeviceBidModifierOutcome,
  type DeviceBidModifierResult,
} from "@/integrations/google_ads/components/device-bid-modifier-outcome"
import { CampaignFailure } from "@/integrations/google_ads/components/campaign-outcome"
import { formatDeviceBidAdjustment } from "@/integrations/google_ads/lib/device-bid-modifiers"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"
import { isOneOf, isRecord } from "@/lib/guards"

const DEVICES = new Set(["DESKTOP", "MOBILE", "TABLET"] as const)
const OUTCOMES = new Set(["updated", "already_set", "failed"] as const)

type DeviceBidModifierArgs = {
  adjustments: DeviceAdjustment[]
  campaignIds: string[]
  campaignLabels: string[]
}

export const googleAdsDeviceBidModifiersPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-update-device-bid-modifiers",
  variants: {
    google_ads_update_device_bid_modifiers: defineGoogleAdsWriteVariant({
      approval: {
        approveLabel: "Approve & Update",
        label: "Update Google Ads Device Bid Adjustments",
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
        title: "Update Device Bid Adjustments",
        validateArgs: deviceBidModifierArgsError,
      },
      deniedDescription: "This device bid adjustment was declined. Nothing was changed.",
      details: deviceBidModifierDetails,
      emptyLabel: "No Google Ads accounts changed device bid adjustments.",
      failedDescription: "The update did not finish. No device bid adjustment was confirmed.",
      heading: "Update Device Bid Adjustments",
      malformedDescription:
        "The system couldn't verify this account's device bid adjustment outcomes. Check the Google Ads platform before taking further action.",
      parseResult: deviceBidModifierResult,
      progressLabel: "Updating Google Ads device bid adjustments…",
      renderFailure: (args, description) => (
        <CampaignFailure args={rawCampaignArgs(args)} description={description} />
      ),
      renderOutcome: (result) => <DeviceBidModifierOutcomeCard result={result} />,
      resultAriaLabel: "Google Ads device bid adjustment results",
      resultFailure:
        "The system couldn't verify the device bid adjustment changes. Check the Google Ads platform before taking further action.",
      unconfirmedAriaLabel: "Unconfirmed Google Ads device bid adjustment update",
      unverifiedDescription:
        "The system couldn't verify whether Google Ads applied these device bid adjustments. Check the Google Ads platform before taking further action.",
      waitingLabel: "Waiting for device bid adjustment approval…",
    }),
  },
})

function deviceBidModifierArgs(value: unknown): DeviceBidModifierArgs | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["campaign_ids"]) ||
    value["campaign_ids"].length === 0 ||
    !Array.isArray(value["adjustments"]) ||
    value["adjustments"].length === 0
  ) {
    return null
  }
  const campaignIds: string[] = []
  const campaignLabels: string[] = []
  for (const campaign of value["campaign_ids"]) {
    if (!isRecord(campaign) || typeof campaign["campaign_id"] !== "string") {
      return null
    }
    const campaignId = campaign["campaign_id"].trim()
    if (!campaignId) {
      return null
    }
    campaignIds.push(campaignId)
    const label = typeof campaign["label"] === "string" ? campaign["label"].trim() : ""
    campaignLabels.push(label || campaignId)
  }
  const adjustments: DeviceAdjustment[] = []
  const seenDevices = new Set<DeviceAdjustment["device"]>()
  for (const item of value["adjustments"]) {
    if (
      !isRecord(item) ||
      !isOneOf(DEVICES, item["device"]) ||
      typeof item["bid_modifier"] !== "number" ||
      !Number.isFinite(item["bid_modifier"]) ||
      (item["bid_modifier"] !== 0 && (item["bid_modifier"] < 0.1 || item["bid_modifier"] > 10)) ||
      seenDevices.has(item["device"])
    ) {
      return null
    }
    seenDevices.add(item["device"])
    adjustments.push({ bidModifier: item["bid_modifier"], device: item["device"] })
  }
  return { adjustments, campaignIds, campaignLabels }
}

function deviceBidModifierArgsError(value: unknown): string | null {
  if (!isRecord(value) || !Array.isArray(value["adjustments"])) {
    return "Review the device bid adjustment fields before approving."
  }
  const seenDevices = new Set<DeviceAdjustment["device"]>()
  for (const item of value["adjustments"]) {
    if (!isRecord(item) || !isOneOf(DEVICES, item["device"])) {
      return "Choose desktop, mobile, or tablet for every row before approving."
    }
    if (
      typeof item["bid_modifier"] !== "number" ||
      !Number.isFinite(item["bid_modifier"]) ||
      (item["bid_modifier"] !== 0 && (item["bid_modifier"] < 0.1 || item["bid_modifier"] > 10))
    ) {
      return "Set each bid modifier to 0 or between 0.1 and 10 before approving."
    }
    if (seenDevices.has(item["device"])) {
      return "Choose each device only once before approving."
    }
    seenDevices.add(item["device"])
  }
  return deviceBidModifierArgs(value)
    ? null
    : "Review the device bid adjustment fields before approving."
}

function deviceBidModifierDetails(args: DeviceBidModifierArgs | null) {
  if (!args) {
    return []
  }
  return [
    { label: "Campaigns", value: args.campaignLabels.join(", ") },
    {
      label: "Adjustments",
      value: args.adjustments
        .map((item) => `${item.device}: ${formatDeviceBidAdjustment(item.bidModifier)}`)
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
  const previous = value["previous_bid_modifier"]
  if (previous !== null && previous !== undefined && !isFiniteNumber(previous)) {
    return null
  }
  const externalRef = optionalString(value["external_ref"])
  const message = optionalString(value["message"])
  const errorCode = optionalString(value["error_code"])
  const note = optionalString(value["note"])
  if (
    externalRef === undefined ||
    message === undefined ||
    errorCode === undefined ||
    note === undefined ||
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
    previousBidModifier: previous ?? null,
  }
}

function optionalString(value: unknown): string | null | undefined {
  return value === null || value === undefined
    ? null
    : typeof value === "string"
      ? value
      : undefined
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value)
}

function rawCampaignArgs(args: DeviceBidModifierArgs | null): unknown {
  return args
    ? {
        campaign_ids: args.campaignIds.map((campaignId, index) => ({
          campaign_id: campaignId,
          label: args.campaignLabels[index] ?? campaignId,
        })),
      }
    : null
}
