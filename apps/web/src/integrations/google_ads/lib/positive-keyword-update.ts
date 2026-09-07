// apps/web/src/integrations/google_ads/lib/positive-keyword-update.ts

import type {
  PositiveKeywordReference,
  PositiveKeywordStatus,
} from "@/integrations/google_ads/lib/positive-keywords"

export const POSITIVE_KEYWORD_PATCH_FIELDS = [
  {
    advanced: false,
    key: "status",
    label: "Status",
    updateMask: "status",
    valueFamily: "status",
  },
  {
    advanced: true,
    key: "bid_modifier",
    label: "Bid adjustment",
    updateMask: "bidModifier",
    valueFamily: "number",
  },
  {
    advanced: false,
    key: "cpc_bid",
    label: "CPC bid",
    updateMask: "cpcBidMicros",
    valueFamily: "money",
  },
  {
    advanced: true,
    key: "final_urls",
    label: "Final URLs",
    updateMask: "finalUrls",
    valueFamily: "urlList",
  },
  {
    advanced: true,
    key: "final_mobile_urls",
    label: "Mobile URLs",
    updateMask: "finalMobileUrls",
    valueFamily: "urlList",
  },
  {
    advanced: true,
    key: "final_url_suffix",
    label: "Final URL suffix",
    updateMask: "finalUrlSuffix",
    valueFamily: "text",
  },
  {
    advanced: true,
    key: "tracking_url_template",
    label: "Tracking template",
    updateMask: "trackingUrlTemplate",
    valueFamily: "text",
  },
  {
    advanced: true,
    key: "url_custom_parameters",
    label: "URL parameters",
    updateMask: "urlCustomParameters",
    valueFamily: "parameters",
  },
] as const

export type PatchField = (typeof POSITIVE_KEYWORD_PATCH_FIELDS)[number]["key"]

export type MutableKeywordState = {
  status: PositiveKeywordStatus
  bid_modifier: number | null
  cpc_bid: string | null
  final_urls: string[]
  final_mobile_urls: string[]
  final_url_suffix: string | null
  tracking_url_template: string | null
  url_custom_parameters: Record<string, string>
}

export type KeywordPatch = Partial<MutableKeywordState>

export type PositiveKeywordUpdateArgs = {
  accounts: Map<string, { currencyCode: string; label: string }>
  keywords: PositiveKeywordReference[]
  patches: KeywordPatch[]
}

export const POSITIVE_KEYWORD_PATCH_FIELD_SET: ReadonlySet<string> = new Set(
  POSITIVE_KEYWORD_PATCH_FIELDS.map((field) => field.key)
)

export const POSITIVE_KEYWORD_PATCH_FIELDS_BY_KEY = new Map(
  POSITIVE_KEYWORD_PATCH_FIELDS.map((field) => [field.key, field] as const)
)

export function mutableStateFromReference(
  reference: PositiveKeywordReference
): MutableKeywordState {
  return {
    status: reference.status,
    bid_modifier: reference.bidModifier,
    cpc_bid: reference.cpcBid,
    final_urls: reference.finalUrls,
    final_mobile_urls: reference.finalMobileUrls,
    final_url_suffix: reference.finalUrlSuffix,
    tracking_url_template: reference.trackingUrlTemplate,
    url_custom_parameters: reference.urlCustomParameters,
  }
}

export function replacePositiveKeywordPatch(
  patches: KeywordPatch[],
  rowIndex: number,
  patch: KeywordPatch
): KeywordPatch[] {
  return patches.map((current, index) => (index === rowIndex ? patch : current))
}

export function formatPositiveKeywordValue(
  field: PatchField,
  value: MutableKeywordState[PatchField],
  currencyCode: string
): string {
  if (value === null) return "Cleared"
  if (Array.isArray(value)) return value.length ? value.join(" · ") : "Cleared"
  if (typeof value === "object") {
    const entries = Object.entries(value)
    return entries.length ? entries.map(([key, item]) => `{${key}}=${item}`).join(" · ") : "Cleared"
  }
  if (field === "status") return value === "ENABLED" ? "Enabled" : "Paused"
  if (field === "cpc_bid") return `${String(value)} ${currencyCode}`
  return String(value)
}
