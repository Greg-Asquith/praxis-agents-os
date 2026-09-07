// apps/web/src/integrations/google_ads/lib/positive-keywords.ts

import {
  googleAdsId,
  parseGoogleAdsMoney,
  parseGoogleAdsUrlList,
  parseGoogleAdsCustomParameters,
} from "@/integrations/google_ads/lib/field-values"
import { isRecord } from "@/lib/guards"

type PositiveKeywordMatchType = "EXACT" | "PHRASE" | "BROAD"
export type PositiveKeywordStatus = "ENABLED" | "PAUSED"

const POSITIVE_KEYWORD_MATCH_TYPES: ReadonlySet<PositiveKeywordMatchType> = new Set([
  "EXACT",
  "PHRASE",
  "BROAD",
])
const POSITIVE_KEYWORD_STATUSES: ReadonlySet<PositiveKeywordStatus> = new Set(["ENABLED", "PAUSED"])

export type PositiveKeywordInput = {
  bidModifier: number | null
  cpcBid: string | null
  finalMobileUrls: string[]
  finalUrls: string[]
  finalUrlSuffix: string | null
  matchType: PositiveKeywordMatchType
  status: PositiveKeywordStatus
  text: string
  trackingUrlTemplate: string | null
  urlCustomParameters: Record<string, string>
}

type PositiveKeywordCore = Pick<PositiveKeywordInput, "matchType" | "status" | "text">
type PositiveKeywordUrls = Pick<
  PositiveKeywordInput,
  "finalMobileUrls" | "finalUrls" | "finalUrlSuffix" | "trackingUrlTemplate"
>

export function parsePositiveKeywordInput(value: unknown): PositiveKeywordInput | null {
  if (!isRecord(value)) return null
  const core = positiveKeywordCore(value)
  const urls = positiveKeywordUrls(value)
  if (!core || !urls) return null
  const cpcBid = optionalMoneyBid(value["cpc_bid"])
  if (cpcBid === undefined) return null
  const bidModifier = optionalBidModifier(value["bid_modifier"])
  if (bidModifier === undefined) return null
  const urlCustomParameters = parseGoogleAdsCustomParameters(value["url_custom_parameters"] ?? {})
  if (urlCustomParameters === undefined) return null
  return { ...core, ...urls, bidModifier, cpcBid, urlCustomParameters }
}

function positiveKeywordCore(value: Record<string, unknown>): PositiveKeywordCore | null {
  const text = typeof value["text"] === "string" ? value["text"].trim().replace(/\s+/g, " ") : ""
  const matchType = value["match_type"]
  const status = value["status"] ?? "ENABLED"
  if (
    text.length < 1 ||
    text.length > 80 ||
    text.split(" ").length > 10 ||
    typeof matchType !== "string" ||
    !POSITIVE_KEYWORD_MATCH_TYPES.has(matchType as PositiveKeywordMatchType) ||
    typeof status !== "string" ||
    !POSITIVE_KEYWORD_STATUSES.has(status as PositiveKeywordStatus)
  ) {
    return null
  }
  return {
    matchType: matchType as PositiveKeywordMatchType,
    status: status as PositiveKeywordStatus,
    text,
  }
}

function positiveKeywordUrls(value: Record<string, unknown>): PositiveKeywordUrls | null {
  const finalUrls = urlList(value["final_urls"])
  const finalMobileUrls = urlList(value["final_mobile_urls"])
  const [finalUrlSuffix, trackingUrlTemplate] = [
    value["final_url_suffix"],
    value["tracking_url_template"],
  ].map((text) => {
    if (text == null || (typeof text === "string" && !text.trim())) return null
    return typeof text === "string" && text.length <= 2048 ? text : undefined
  })
  if (
    finalUrls === null ||
    finalMobileUrls === null ||
    finalUrlSuffix === undefined ||
    trackingUrlTemplate === undefined
  )
    return null
  if (trackingUrlTemplate !== null && finalUrls.length === 0) return null
  return { finalUrls, finalMobileUrls, finalUrlSuffix, trackingUrlTemplate }
}

export function positiveKeywordInputValidationError(value: unknown): string | null {
  if (!isRecord(value)) return "Each keyword row must contain valid fields."
  if (parseGoogleAdsCustomParameters(value["url_custom_parameters"] ?? {}) === undefined) {
    return (
      "URL custom parameters accept at most eight entries. Names must use 1-16 ASCII letters " +
      "or numbers and be unique ignoring case. Values can use at most 200 UTF-8 bytes."
    )
  }
  if (optionalMoneyBid(value["cpc_bid"]) === undefined) {
    return "CPC bids must be positive, use at most six decimal places, and fit Google Ads' limit."
  }
  if (optionalBidModifier(value["bid_modifier"]) === undefined) {
    return "Bid adjustments must be a number from 0.1 through 10."
  }
  const finalUrls = urlList(value["final_urls"])
  const trackingTemplate = value["tracking_url_template"]
  if (
    typeof trackingTemplate === "string" &&
    trackingTemplate.trim() &&
    trackingTemplate.length <= 2048 &&
    finalUrls?.length === 0
  ) {
    return "Add at least one final URL when using a tracking URL template."
  }
  return parsePositiveKeywordInput(value) ? null : "Review the invalid keyword fields."
}

function optionalMoneyBid(value: unknown): string | null | undefined {
  if (value == null || (typeof value === "string" && !value.trim())) return null
  return parseGoogleAdsMoney(typeof value === "string" ? value.trim() : value)
}

function optionalBidModifier(value: unknown): number | null | undefined {
  if (value == null || value === "") return null
  if (typeof value !== "number" || !Number.isFinite(value)) return undefined
  return value >= 0.1 && value <= 10 ? value : undefined
}

function urlList(value: unknown): string[] | null {
  if (value == null) return []
  if (!Array.isArray(value)) return null
  return (
    parseGoogleAdsUrlList(
      value.map((url: unknown) => (typeof url === "string" ? url.trim() : url))
    ) ?? null
  )
}

export type PositiveKeywordReference = PositiveKeywordInput & {
  adGroupId: string
  campaignId: string
  criterionId: string
  customerId: string
  identity: string
  label: string
  scopeLabel: string
}

export function parsePositiveKeywordReference(value: unknown): PositiveKeywordReference | null {
  if (!isRecord(value)) return null
  const identity = positiveKeywordReferenceIdentity(value)
  if (!identity) return null
  const bids = positiveKeywordReferenceBids(value)
  if (!bids) return null
  const configuration = parsePositiveKeywordInput({
    ...value,
    cpc_bid: bids.cpcBid === "0" ? null : bids.cpcBid,
  })
  if (!configuration) return null
  return {
    ...identity,
    ...configuration,
    ...bids,
    label:
      typeof value["label"] === "string" && value["label"].trim()
        ? value["label"]
        : configuration.text,
    scopeLabel:
      typeof value["scope_label"] === "string" && value["scope_label"].trim()
        ? value["scope_label"]
        : "Campaign and ad group unavailable",
  }
}

function positiveKeywordReferenceBids(
  value: Record<string, unknown>
): Pick<PositiveKeywordReference, "bidModifier" | "cpcBid"> | null {
  const cpcBid = microsDecimal(value["cpc_bid_micros"])
  const rawBidModifier = value["bid_modifier"]
  const bidModifier =
    rawBidModifier == null
      ? null
      : typeof rawBidModifier === "number" &&
          Number.isFinite(rawBidModifier) &&
          rawBidModifier >= 0.1 &&
          rawBidModifier <= 10
        ? rawBidModifier
        : undefined
  return cpcBid === undefined || bidModifier === undefined ? null : { bidModifier, cpcBid }
}

function positiveKeywordReferenceIdentity(
  value: Record<string, unknown>
): Pick<
  PositiveKeywordReference,
  "adGroupId" | "campaignId" | "criterionId" | "customerId" | "identity"
> | null {
  if (value["entity_kind"] != null && value["entity_kind"] !== "google_ads_keyword") return null
  if (typeof value["label"] !== "string") return null
  const customerId = googleAdsId(value["customer_id"])
  const campaignId = googleAdsId(value["campaign_id"])
  const adGroupId = googleAdsId(value["ad_group_id"])
  const criterionId = googleAdsId(value["criterion_id"])
  if (!customerId || !campaignId || !adGroupId || !criterionId) return null
  return {
    adGroupId,
    campaignId,
    criterionId,
    customerId,
    identity: `${customerId}:${adGroupId}:${criterionId}`,
  }
}

function microsDecimal(value: unknown): string | null | undefined {
  if (value == null) return null
  if (typeof value !== "string" || !/^\d+$/.test(value)) return undefined
  const micros = BigInt(value)
  if (micros > 9223372036854775807n) return undefined
  const whole = micros / 1_000_000n
  const fraction = String(micros % 1_000_000n)
    .padStart(6, "0")
    .replace(/0+$/, "")
  return fraction ? `${String(whole)}.${fraction}` : String(whole)
}
