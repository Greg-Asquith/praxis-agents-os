// apps/web/src/integrations/google_ads/lib/positive-keywords.ts

import { isRecord, parsePositiveDecimal } from "@/lib/guards"

export type PositiveKeywordMatchType = "EXACT" | "PHRASE" | "BROAD"
export type PositiveKeywordStatus = "ENABLED" | "PAUSED"

export const GOOGLE_ADS_ID_PATTERN = /^\d+$/
export const POSITIVE_KEYWORD_MATCH_TYPES: ReadonlySet<PositiveKeywordMatchType> = new Set([
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
}

export type PositiveKeywordInput = {
  cpcBid: string | null
  matchType: PositiveKeywordMatchType
  text: string
}

export function parsePositiveKeywordInput(value: unknown): PositiveKeywordInput | null {
  if (!isRecord(value)) return null
  const text = typeof value["text"] === "string" ? value["text"].trim().replace(/\s+/g, " ") : ""
  const matchType = value["match_type"]
  const cpcBid = value["cpc_bid"]
  if (
    text.length < 1 ||
    text.length > 80 ||
    text.split(" ").length > 10 ||
    typeof matchType !== "string" ||
    !POSITIVE_KEYWORD_MATCH_TYPES.has(matchType as PositiveKeywordMatchType) ||
    (cpcBid != null &&
      (typeof cpcBid !== "string" ||
        (cpcBid.trim().length > 0 && parsePositiveDecimal(cpcBid) === null)))
  ) {
    return null
  }
  return {
    cpcBid: typeof cpcBid === "string" && cpcBid.trim() ? cpcBid.trim() : null,
    matchType: matchType as PositiveKeywordMatchType,
    text,
  }
}

export function parsePositiveKeywordReference(value: unknown): PositiveKeywordReference | null {
  if (!isRecord(value)) return null
  const customerId = value["customer_id"]
  const campaignId = value["campaign_id"]
  const adGroupId = value["ad_group_id"]
  const criterionId = value["criterion_id"]
  const matchType = value["match_type"]
  const status = value["status"]
  if (
    (value["entity_kind"] != null && value["entity_kind"] !== "google_ads_keyword") ||
    typeof customerId !== "string" ||
    !GOOGLE_ADS_ID_PATTERN.test(customerId) ||
    typeof campaignId !== "string" ||
    !GOOGLE_ADS_ID_PATTERN.test(campaignId) ||
    typeof adGroupId !== "string" ||
    !GOOGLE_ADS_ID_PATTERN.test(adGroupId) ||
    typeof criterionId !== "string" ||
    !GOOGLE_ADS_ID_PATTERN.test(criterionId) ||
    typeof value["label"] !== "string" ||
    typeof value["text"] !== "string" ||
    typeof matchType !== "string" ||
    !POSITIVE_KEYWORD_MATCH_TYPES.has(matchType as PositiveKeywordMatchType) ||
    typeof status !== "string" ||
    !POSITIVE_KEYWORD_STATUSES.has(status as PositiveKeywordStatus) ||
    (value["scope_label"] != null && typeof value["scope_label"] !== "string")
  ) {
    return null
  }
  const text = value["text"].trim()
  if (!text || text.length > 80) return null
  return {
    adGroupId,
    campaignId,
    criterionId,
    customerId,
    identity: `${customerId}:${adGroupId}:${criterionId}`,
    label: value["label"].trim() || text,
    matchType: matchType as PositiveKeywordMatchType,
    scopeLabel:
      typeof value["scope_label"] === "string" && value["scope_label"].trim()
        ? value["scope_label"]
        : "Campaign and ad group unavailable",
    status: status as PositiveKeywordStatus,
    text,
  }
}
