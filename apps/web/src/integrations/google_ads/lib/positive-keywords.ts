// apps/web/src/integrations/google_ads/lib/positive-keywords.ts

import { isRecord } from "@/lib/guards"

type PositiveKeywordMatchType = "EXACT" | "PHRASE" | "BROAD"
export type PositiveKeywordStatus = "ENABLED" | "PAUSED"

export const GOOGLE_ADS_ID_PATTERN = /^\d+$/
const POSITIVE_KEYWORD_MATCH_TYPES: ReadonlySet<PositiveKeywordMatchType> = new Set([
  "EXACT",
  "PHRASE",
  "BROAD",
])
const POSITIVE_KEYWORD_STATUSES: ReadonlySet<PositiveKeywordStatus> = new Set(["ENABLED", "PAUSED"])

export type PositiveKeywordReference = {
  adGroupId: string
  campaignId: string
  criterionId: string
  customerId: string
  identity: string
  label: string
  matchType: PositiveKeywordMatchType
  scopeLabel: string
  status: PositiveKeywordStatus
  text: string
  bidModifier: number | null
  cpcBid: string | null
  finalMobileUrls: string[]
  finalUrls: string[]
  finalUrlSuffix: string | null
  trackingUrlTemplate: string | null
  urlCustomParameters: Record<string, string>
}

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
  const urlCustomParameters = customParameters(value["url_custom_parameters"])
  if (urlCustomParameters === null) return null
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
  const finalUrlSuffix = optionalBoundedString(value["final_url_suffix"], 2048)
  const trackingUrlTemplate = optionalBoundedString(value["tracking_url_template"], 2048)
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
  if (customParameters(value["url_custom_parameters"]) === null) {
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
  const trackingTemplate = optionalBoundedString(value["tracking_url_template"], 2048)
  if (trackingTemplate && finalUrls?.length === 0) {
    return "Add at least one final URL when using a tracking URL template."
  }
  return parsePositiveKeywordInput(value) ? null : "Review the invalid keyword fields."
}

const GOOGLE_ADS_INT64_MAX = 9223372036854775807n

function optionalMoneyBid(value: unknown): string | null | undefined {
  if (value == null || (typeof value === "string" && !value.trim())) return null
  if (typeof value !== "string" || !/^\d+(?:\.\d{1,6})?$/.test(value.trim())) return undefined
  const candidate = value.trim()
  const [whole = "0", fraction = ""] = candidate.split(".")
  const micros = BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, "0"))
  return micros > 0n && micros <= GOOGLE_ADS_INT64_MAX ? candidate : undefined
}

function optionalBidModifier(value: unknown): number | null | undefined {
  if (value == null || value === "") return null
  if (typeof value !== "number" || !Number.isFinite(value)) return undefined
  return value >= 0.1 && value <= 10 ? value : undefined
}

function urlList(value: unknown): string[] | null {
  if (value == null) return []
  if (!Array.isArray(value) || value.length > 10) return null
  const urls = value
    .filter((item): item is string => typeof item === "string")
    .map((url) => url.trim())
  if (
    urls.length !== value.length ||
    urls.some((url) => url.length > 2048 || !/^https?:\/\/\S+$/i.test(url))
  )
    return null
  return urls
}

function optionalBoundedString(value: unknown, maximum: number): string | null | undefined {
  if (value == null || (typeof value === "string" && !value.trim())) return null
  return typeof value === "string" && value.length <= maximum ? value : undefined
}

function validCustomParameter(key: string, value: string): boolean {
  return (
    /^[A-Za-z0-9]+$/.test(key) &&
    new TextEncoder().encode(key).length <= 16 &&
    new TextEncoder().encode(value).length <= 200
  )
}

function customParameterEntries(value: unknown): [string, string][] | null {
  if (value == null) return []
  if (Array.isArray(value)) return customParameterArrayEntries(value)
  if (!isRecord(value) || Object.keys(value).length > 8) return null
  const entries = Object.entries(value)
  return entries.every(
    (entry): entry is [string, string] =>
      typeof entry[1] === "string" && validCustomParameter(entry[0], entry[1])
  )
    ? entries
    : null
}

function customParameterArrayEntries(value: unknown[]): [string, string][] | null {
  if (value.length > 8) return null
  const entries: [string, string][] = []
  for (const item of value) {
    if (!isRecord(item)) return null
    const key = item["key"]
    const parameterValue = item["value"]
    if (typeof key !== "string" || typeof parameterValue !== "string") return null
    if (!validCustomParameter(key, parameterValue)) return null
    entries.push([key, parameterValue])
  }
  return entries
}

function customParameters(value: unknown): Record<string, string> | null {
  const entries = customParameterEntries(value)
  if (entries === null) return null
  const normalizedKeys = new Set<string>()
  const parameters: Record<string, string> = {}
  for (const [key, item] of entries) {
    const normalized = key.toLowerCase()
    if (normalizedKeys.has(normalized)) return null
    normalizedKeys.add(normalized)
    parameters[key] = item
  }
  return parameters
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
    label: keywordReferenceLabel(value["label"], configuration.text),
    scopeLabel: keywordReferenceScopeLabel(value["scope_label"]),
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

function keywordReferenceLabel(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value : fallback
}

function keywordReferenceScopeLabel(value: unknown): string {
  return typeof value === "string" && value.trim() ? value : "Campaign and ad group unavailable"
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

function googleAdsId(value: unknown): string | null {
  return typeof value === "string" && GOOGLE_ADS_ID_PATTERN.test(value) ? value : null
}

function microsDecimal(value: unknown): string | null | undefined {
  if (value == null) return null
  if (typeof value !== "string" || !/^\d+$/.test(value)) return undefined
  const micros = BigInt(value)
  if (micros > GOOGLE_ADS_INT64_MAX) return undefined
  const whole = micros / 1_000_000n
  const fraction = String(micros % 1_000_000n)
    .padStart(6, "0")
    .replace(/0+$/, "")
  return fraction ? `${String(whole)}.${fraction}` : String(whole)
}
