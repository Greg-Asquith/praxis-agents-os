// apps/web/src/integrations/google_ads/lib/device-bid-modifier-inputs.ts

import type { DeviceAdjustment } from "@/integrations/google_ads/components/device-bid-modifier-outcome"
import { isOneOf, isRecord } from "@/lib/guards"
export const DEVICES = new Set(["DESKTOP", "MOBILE", "TABLET"] as const)

export type DeviceBidModifierArgs = {
  adjustments: DeviceAdjustment[]
  campaignIds: string[]
  campaignLabels: string[]
}

export function deviceBidModifierArgs(value: unknown): DeviceBidModifierArgs | null {
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

export function deviceBidModifierArgsError(value: unknown): string | null {
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
