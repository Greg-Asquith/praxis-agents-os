// apps/web/src/integrations/google_ads/lib/positive-keyword-update.ts

import { parseAccountCurrencies } from "@/integrations/google_ads/lib/accounts"
import { parseOutcomeEnvelope } from "@/integrations/google_ads/lib/envelopes"
import {
  parseGoogleAdsCustomParameters,
  parseGoogleAdsMoney,
  parseGoogleAdsUrlList,
} from "@/integrations/google_ads/lib/field-values"
import {
  parsePositiveKeywordReference,
  type PositiveKeywordReference,
  type PositiveKeywordStatus,
} from "@/integrations/google_ads/lib/positive-keywords"
import { isNullableString, isRecord } from "@/lib/guards"

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

const POSITIVE_KEYWORD_PATCH_FIELD_SET: ReadonlySet<string> = new Set(
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

export const OUTCOMES = ["updated", "already_set", "failed", "unverified"] as const

const PATCH_FIELDS = POSITIVE_KEYWORD_PATCH_FIELDS.map((field) => field.key)

type KeywordOutcome = (typeof OUTCOMES)[number]

type UpdateKeywordRow = {
  before: MutableKeywordState
  errorCode: string | null
  message: string | null
  outcome: KeywordOutcome
  reference: PositiveKeywordReference
  requested: MutableKeywordState
  requestedFields: PatchField[]
  updateMask: string
}

export type UpdateKeywordResult = {
  counts: Record<KeywordOutcome, number>
  currencyCode: string
  rows: UpdateKeywordRow[]
}

export function updateKeywordArgs(
  value: unknown,
  parseRow: (value: unknown) => KeywordPatch | null = parsePatch
): PositiveKeywordUpdateArgs | null {
  const arrays = updateKeywordArrays(value)
  if (!arrays || !isRecord(value)) return null
  const keywords = parseKeywordReferences(arrays.keywords)
  const patches = parseKeywordPatches(arrays.patches, parseRow)
  if (!keywords || !patches) return null
  const accounts = parseAccountCurrencies(value["_account_currencies"])
  if (keywords.some((keyword) => !accounts.has(keyword.customerId))) return null
  return { accounts, keywords, patches }
}

function updateKeywordArrays(value: unknown): { keywords: unknown[]; patches: unknown[] } | null {
  if (!isRecord(value)) return null
  const keywords = value["keywords"]
  const patches = value["patches"]
  if (!Array.isArray(keywords) || !Array.isArray(patches)) return null
  if (keywords.length < 1 || keywords.length > 500 || patches.length !== keywords.length)
    return null
  return { keywords, patches }
}

function parseKeywordReferences(values: unknown[]): PositiveKeywordReference[] | null {
  const keywords: PositiveKeywordReference[] = []
  const identities = new Set<string>()
  for (const value of values) {
    const keyword = parsePositiveKeywordReference(value)
    if (!keyword || identities.has(keyword.identity)) return null
    identities.add(keyword.identity)
    keywords.push(keyword)
  }
  return keywords
}

function parseKeywordPatches(
  values: unknown[],
  parseRow: (value: unknown) => KeywordPatch | null
): KeywordPatch[] | null {
  const patches: KeywordPatch[] = []
  for (const value of values) {
    const patch = parseRow(value)
    if (!patch) return null
    patches.push(patch)
  }
  return patches
}

export function updateKeywordArgsValidationError(value: unknown): string | null {
  const args = updateKeywordArgs(value)
  if (!args) return "Provide one valid change row for each selected keyword."
  for (let index = 0; index < args.keywords.length; index += 1) {
    const keyword = args.keywords[index]
    const patch = args.patches[index]
    if (!keyword || !patch) return "Provide one valid change row for each selected keyword."
    const after = { ...mutableStateFromReference(keyword), ...patch }
    const changesDestination = (["final_urls", "tracking_url_template"] as const).some(
      (field) =>
        Object.hasOwn(patch, field) &&
        !valuesEqual(mutableStateFromReference(keyword)[field], after[field])
    )
    if (changesDestination && after.tracking_url_template && after.final_urls.length === 0) {
      return `Add at least one final URL for “${keyword.text}” when using a tracking template.`
    }
  }
  return null
}

function parsePatch(value: unknown): KeywordPatch | null {
  if (!isRecord(value)) return null
  const keys = Object.keys(value)
  if (keys.length < 1 || keys.some((key) => !POSITIVE_KEYWORD_PATCH_FIELD_SET.has(key))) return null
  const patch: KeywordPatch = {}
  for (const field of PATCH_FIELDS) {
    if (!Object.hasOwn(value, field)) continue
    const parsed = parsePatchValue(field, value[field])
    if (parsed === INVALID) return null
    Object.assign(patch, { [field]: parsed })
  }
  return patch
}

const INVALID = Symbol("invalid")

export function parsePatchDraft(value: unknown): KeywordPatch | null {
  if (!isRecord(value)) return null
  if (Object.keys(value).some((key) => !POSITIVE_KEYWORD_PATCH_FIELD_SET.has(key))) return null
  const draft: KeywordPatch = {}
  for (const field of PATCH_FIELDS) {
    if (!Object.hasOwn(value, field)) continue
    const cell = value[field]
    if (!validDraftCell(field, cell)) return null
    Object.assign(draft, { [field]: cell === "" ? null : cell })
  }
  return draft
}

function validDraftCell(field: PatchField, value: unknown): boolean {
  switch (POSITIVE_KEYWORD_PATCH_FIELDS_BY_KEY.get(field)?.valueFamily) {
    case "status":
      return value === "ENABLED" || value === "PAUSED"
    case "number":
      return value === null || value === "" || (typeof value === "number" && Number.isFinite(value))
    case "urlList":
      return Array.isArray(value) && value.every((item) => typeof item === "string")
    case "parameters":
      return isRecord(value) && Object.values(value).every((item) => typeof item === "string")
    case "text":
    case "money":
      return value === null || typeof value === "string"
    case undefined:
      return false
  }
}

function parsePatchValue(
  field: PatchField,
  value: unknown
): MutableKeywordState[PatchField] | typeof INVALID {
  const family = POSITIVE_KEYWORD_PATCH_FIELDS_BY_KEY.get(field)?.valueFamily
  if (family === "status") return value === "ENABLED" || value === "PAUSED" ? value : INVALID
  if (family === "number") return nullableBidModifier(value)
  return parseStructuredPatchValue(family, value)
}

function parseStructuredPatchValue(
  family: "money" | "parameters" | "text" | "urlList" | undefined,
  value: unknown
): MutableKeywordState[PatchField] | typeof INVALID {
  switch (family) {
    case "money":
      return value === null || value === "" ? null : (parseGoogleAdsMoney(value) ?? INVALID)
    case "urlList":
      return parseGoogleAdsUrlList(value) ?? INVALID
    case "parameters":
      return isRecord(value) ? (parseGoogleAdsCustomParameters(value) ?? INVALID) : INVALID
    case "text":
      return value === null || value === ""
        ? null
        : typeof value === "string" && value.length <= 2048
          ? value
          : INVALID
    case undefined:
      return INVALID
  }
}

function nullableBidModifier(value: unknown): number | null | typeof INVALID {
  if (value === null || value === "") return null
  return typeof value === "number" && Number.isFinite(value) && value >= 0.1 && value <= 10
    ? value
    : INVALID
}

export function updateKeywordResult(value: unknown): UpdateKeywordResult | null {
  if (!isRecord(value)) return null
  const currencyCode = value["currency_code"]
  if (typeof currencyCode !== "string" || !currencyCode.trim()) return null
  if (value["samples_truncated"] !== false) return null
  const parsed = parseOutcomeEnvelope(value, OUTCOMES, parseResultRow)
  if (!parsed) return null
  const total = OUTCOMES.reduce((sum, outcome) => sum + parsed.counts[outcome], 0)
  if (parsed.rows.length !== total) return null
  if (new Set(parsed.rows.map((row) => row.reference.identity)).size !== total) return null
  return { counts: parsed.counts, currencyCode, rows: parsed.rows }
}

function parseResultRow(value: unknown, outcome: KeywordOutcome): UpdateKeywordRow | null {
  if (!isRecord(value)) return null
  const reference = parsePositiveKeywordReference(value["keyword"])
  const before = parseState(value["before"])
  const requested = parseState(value["requested"])
  const requestedFields = parseRequestedFields(value["requested_fields"])
  const diagnostics = parseResultDiagnostics(value)
  if (!reference || !before || !requested || !requestedFields || !diagnostics) return null
  if (value["outcome"] !== outcome || !validUpdateMask(value["update_mask"], requestedFields))
    return null
  if (!resultStateIsConsistent(reference, before, requested, requestedFields, outcome)) return null
  return {
    before,
    ...diagnostics,
    outcome,
    reference,
    requested,
    requestedFields,
    updateMask: value["update_mask"],
  }
}

function parseRequestedFields(value: unknown): PatchField[] | null {
  if (!Array.isArray(value) || value.length < 1 || new Set(value).size !== value.length) return null
  return value.every(
    (field): field is PatchField =>
      typeof field === "string" && POSITIVE_KEYWORD_PATCH_FIELD_SET.has(field)
  )
    ? value
    : null
}

function validUpdateMask(value: unknown, fields: PatchField[]): value is string {
  if (typeof value !== "string") return false
  return (
    value ===
    fields.map((field) => POSITIVE_KEYWORD_PATCH_FIELDS_BY_KEY.get(field)?.updateMask).join(",")
  )
}

function parseResultDiagnostics(
  value: Record<string, unknown>
): Pick<UpdateKeywordRow, "errorCode" | "message"> | null {
  const errorCode = value["error_code"]
  const message = value["message"]
  if (!isNullableString(value["external_ref"])) return null
  if (!isNullableString(errorCode) || !isNullableString(message)) return null
  return { errorCode, message }
}

function resultStateIsConsistent(
  reference: PositiveKeywordReference,
  before: MutableKeywordState,
  requested: MutableKeywordState,
  requestedFields: PatchField[],
  outcome: KeywordOutcome
): boolean {
  if (
    PATCH_FIELDS.some(
      (field) => !requestedFields.includes(field) && !valuesEqual(before[field], requested[field])
    )
  )
    return false
  const everyValueMatches = requestedFields.every((field) =>
    valuesEqual(before[field], requested[field])
  )
  if ((outcome === "already_set") !== everyValueMatches) return false
  const observed = mutableStateFromReference(reference)
  const expected = outcome === "updated" || outcome === "already_set" ? requested : before
  return PATCH_FIELDS.every((field) => valuesEqual(observed[field], expected[field]))
}

function parseState(value: unknown): MutableKeywordState | null {
  if (!isRecord(value) || Object.keys(value).length !== PATCH_FIELDS.length) return null
  const state: Partial<MutableKeywordState> = {}
  for (const field of PATCH_FIELDS) {
    const parsed = parseStateValue(field, value[field])
    if (parsed === INVALID) return null
    Object.assign(state, { [field]: parsed })
  }
  return state as MutableKeywordState
}

function parseStateValue(
  field: PatchField,
  value: unknown
): MutableKeywordState[PatchField] | typeof INVALID {
  if (field === "url_custom_parameters") return stateCustomParameters(value)
  if (field === "cpc_bid")
    return value === null ? null : (parseGoogleAdsMoney(value, 0n) ?? INVALID)
  return parsePatchValue(field, value)
}

function stateCustomParameters(value: unknown): Record<string, string> | typeof INVALID {
  return parseGoogleAdsCustomParameters(value) ?? INVALID
}

function valuesEqual(
  left: MutableKeywordState[PatchField],
  right: MutableKeywordState[PatchField]
): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}
