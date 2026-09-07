// apps/web/src/integrations/google_ads/presenters/update-positive-keywords.tsx

import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Stat, StatGroup } from "@/components/ui/stat"
import {
  GOOGLE_ADS_ID_PATTERN,
  parsePositiveKeywordReference,
  type PositiveKeywordReference,
} from "@/integrations/google_ads/lib/positive-keywords"
import {
  formatPositiveKeywordValue,
  mutableStateFromReference,
  POSITIVE_KEYWORD_PATCH_FIELDS,
  POSITIVE_KEYWORD_PATCH_FIELDS_BY_KEY,
  POSITIVE_KEYWORD_PATCH_FIELD_SET,
  type KeywordPatch,
  type MutableKeywordState,
  type PatchField,
  type PositiveKeywordUpdateArgs,
} from "@/integrations/google_ads/lib/positive-keyword-update"
import { UpdatePositiveKeywordsApproval } from "@/integrations/google_ads/presenters/update-positive-keywords-approval"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"
import { titleCaseToken } from "@/lib/format"
import { isNonNegativeInteger, isNullableString, isRecord } from "@/lib/guards"

const OUTCOMES = ["updated", "already_set", "failed", "unverified"] as const
const PATCH_FIELDS = POSITIVE_KEYWORD_PATCH_FIELDS.map((field) => field.key)
const CURRENCY_PATTERN = /^[A-Z]{3}$/
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
type UpdateKeywordResult = {
  counts: Record<KeywordOutcome, number>
  currencyCode: string
  rows: UpdateKeywordRow[]
}

const COLUMNS: DataColumn[] = [
  { key: "scope", kind: "text", label: "Campaign · Ad Group" },
  { key: "keyword", kind: "text", label: "Keyword" },
  { key: "matchType", kind: "text", label: "Match Type" },
  { key: "fields", kind: "text", label: "Changed Fields", width: 220 },
  { key: "before", kind: "text", label: "Before", width: 320 },
  { key: "requested", kind: "text", label: "Requested", width: 320 },
  { key: "outcome", kind: "status", label: "Outcome" },
  { key: "details", kind: "text", label: "Details", width: 280 },
]

export const googleAdsUpdatePositiveKeywordsPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-update-positive-keywords",
  variants: {
    google_ads_update_keywords: defineGoogleAdsWriteVariant({
      approval: {
        approveLabel: "Approve & Update",
        label: "Update Google Ads Keywords",
        parseArgs: updateKeywordArgs,
        validateArgs: updateKeywordArgsValidationError,
        prompt: "Review every changed keyword setting. Keyword text and match type stay unchanged.",
        renderFields: false,
        renderInvalidDraft: true,
        renderSummary: (value, _fallback, onFieldEdit, disabled) => {
          const args = updateKeywordArgs(value, parsePatchDraft)
          return args ? (
            <UpdatePositiveKeywordsApproval
              args={args}
              disabled={disabled}
              onChange={(patches) => {
                onFieldEdit("patches", patches)
              }}
            />
          ) : null
        },
        title: "Update Keywords",
      },
      deniedDescription: "This keyword update was declined. Nothing was changed.",
      details: (args) => (args ? [{ label: "Keywords", value: String(args.keywords.length) }] : []),
      emptyLabel: "No Google Ads accounts updated keywords.",
      failedDescription: "The update did not finish. No keyword change was confirmed.",
      heading: "Update Keywords",
      malformedDescription:
        "The system couldn't verify this account's keyword outcomes. Check Google Ads before taking further action.",
      parseResult: updateKeywordResult,
      progressLabel: "Updating Google Ads keywords…",
      renderOutcome,
      resultAriaLabel: "Google Ads positive keyword update results",
      resultFailure:
        "The system couldn't verify the keyword changes. Check Google Ads before taking further action.",
      unconfirmedAriaLabel: "Unconfirmed Google Ads keyword update",
      unverifiedDescription:
        "The system couldn't verify whether Google Ads applied these keyword changes. Check Google Ads before retrying.",
      waitingLabel: "Waiting for keyword approval…",
    }),
  },
})

function renderOutcome(result: UpdateKeywordResult) {
  const rows = result.rows.map<DataRow>((row) => ({
    requested: summarizeFields(row.requested, row.requestedFields, result.currencyCode),
    before: summarizeFields(row.before, row.requestedFields, result.currencyCode),
    details:
      [row.message, row.errorCode ? titleCaseToken(row.errorCode, row.errorCode) : null]
        .filter((value): value is string => Boolean(value))
        .join(" · ") || "—",
    fields: row.requestedFields.map(fieldLabel).join(", "),
    keyword: row.reference.text,
    matchType: titleCaseToken(row.reference.matchType, row.reference.matchType),
    outcome:
      row.outcome === "already_set" ? "Already set" : titleCaseToken(row.outcome, row.outcome),
    scope: row.reference.scopeLabel,
  }))
  return (
    <DataTable
      columns={COLUMNS}
      exportFilename="google-ads-keyword-updates.csv"
      header={
        <StatGroup className="px-3 pt-2">
          <Stat
            label="Updated"
            tone={result.counts.updated > 0 ? "success" : undefined}
            value={result.counts.updated}
          />
          <Stat label="Already set" value={result.counts.already_set} />
          <Stat
            label="Failed"
            tone={result.counts.failed > 0 ? "danger" : undefined}
            value={result.counts.failed}
          />
          <Stat
            label="Unverified"
            tone={result.counts.unverified > 0 ? "warning" : undefined}
            value={result.counts.unverified}
          />
        </StatGroup>
      }
      pageSize={25}
      rows={rows}
    />
  )
}

function updateKeywordArgs(
  value: unknown,
  parseRow: (value: unknown) => KeywordPatch | null = parsePatch
): PositiveKeywordUpdateArgs | null {
  const arrays = updateKeywordArrays(value)
  if (!arrays || !isRecord(value)) return null
  const keywords = parseKeywordReferences(arrays.keywords)
  const patches = parseKeywordPatches(arrays.patches, parseRow)
  if (!keywords || !patches) return null
  const accounts = parseAccounts(value["_account_currencies"])
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

function parseAccounts(value: unknown): Map<string, { currencyCode: string; label: string }> {
  const accounts = new Map<string, { currencyCode: string; label: string }>()
  if (!Array.isArray(value)) return accounts
  for (const item of value) {
    if (!isRecord(item)) continue
    const customerId = item["customer_id"]
    const currencyCode = item["currency_code"]
    const label = item["label"]
    if (
      typeof customerId === "string" &&
      GOOGLE_ADS_ID_PATTERN.test(customerId) &&
      typeof currencyCode === "string" &&
      CURRENCY_PATTERN.test(currencyCode) &&
      typeof label === "string" &&
      label.trim()
    ) {
      accounts.set(customerId, { currencyCode, label })
    }
  }
  return accounts
}

function updateKeywordArgsValidationError(value: unknown): string | null {
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

function parsePatchDraft(value: unknown): KeywordPatch | null {
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
      return nullableMoney(value)
    case "urlList":
      return urlList(value)
    case "parameters":
      return customParameters(value)
    case "text":
      return nullableBoundedText(value)
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

function updateKeywordResult(value: unknown): UpdateKeywordResult | null {
  if (!isRecord(value)) return null
  const currencyCode = value["currency_code"]
  const countsValue = value["counts"]
  const samplesValue = value["samples"]
  if (typeof currencyCode !== "string" || !currencyCode.trim()) return null
  if (!isRecord(countsValue) || !isRecord(samplesValue)) return null
  if (value["samples_truncated"] !== false) return null
  const parsed = parseOutcomeSamples(countsValue, samplesValue)
  if (!parsed) return null
  const total = OUTCOMES.reduce((sum, outcome) => sum + parsed.counts[outcome], 0)
  if (parsed.rows.length !== total) return null
  if (new Set(parsed.rows.map((row) => row.reference.identity)).size !== total) return null
  return { counts: parsed.counts, currencyCode, rows: parsed.rows }
}

function parseOutcomeSamples(
  countsValue: Record<string, unknown>,
  samplesValue: Record<string, unknown>
): Pick<UpdateKeywordResult, "counts" | "rows"> | null {
  const counts = {} as Record<KeywordOutcome, number>
  const rows: UpdateKeywordRow[] = []
  for (const outcome of OUTCOMES) {
    const count = countsValue[outcome]
    const samples = samplesValue[outcome]
    if (!isNonNegativeInteger(count) || !Array.isArray(samples) || samples.length !== count)
      return null
    counts[outcome] = count
    for (const sample of samples) {
      const row = parseResultRow(sample, outcome)
      if (!row) return null
      rows.push(row)
    }
  }
  return { counts, rows }
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
  if (!Array.isArray(value) || value.length < 1) return null
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
  if (field === "cpc_bid") return nullableProviderMoney(value)
  return parsePatchValue(field, value)
}

function stateCustomParameters(value: unknown): Record<string, string> | typeof INVALID {
  if (isRecord(value)) return customParameters(value)
  if (!Array.isArray(value) || value.length > 8) return INVALID
  const parameters: Record<string, string> = {}
  for (const item of value) {
    if (!isRecord(item) || typeof item["key"] !== "string" || typeof item["value"] !== "string") {
      return INVALID
    }
    parameters[item["key"]] = item["value"]
  }
  return customParameters(parameters)
}

function nullableMoney(value: unknown): string | null | typeof INVALID {
  if (value === null || value === "") return null
  if (typeof value !== "string" || !/^\d+(?:\.\d{1,6})?$/.test(value)) return INVALID
  const [whole = "0", fraction = ""] = value.split(".")
  const micros = BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, "0"))
  return micros > 0n && micros <= 9_223_372_036_854_775_807n ? value : INVALID
}

function nullableProviderMoney(value: unknown): string | null | typeof INVALID {
  if (value === null) return null
  if (typeof value !== "string" || !/^\d+(?:\.\d{1,6})?$/.test(value)) return INVALID
  const [whole = "0", fraction = ""] = value.split(".")
  const micros = BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, "0"))
  return micros <= 9_223_372_036_854_775_807n ? value : INVALID
}

function urlList(value: unknown): string[] | typeof INVALID {
  if (!Array.isArray(value) || value.length > 10) return INVALID
  return value.every(
    (url) => typeof url === "string" && url.length <= 2048 && /^https?:\/\/\S+$/i.test(url)
  )
    ? value
    : INVALID
}

function nullableBoundedText(value: unknown): string | null | typeof INVALID {
  if (value === null || value === "") return null
  return typeof value === "string" && value.length <= 2048 ? value : INVALID
}

function customParameters(value: unknown): Record<string, string> | typeof INVALID {
  if (!isRecord(value) || Object.keys(value).length > 8) return INVALID
  const normalized = new Set<string>()
  for (const [key, item] of Object.entries(value)) {
    const folded = key.toLowerCase()
    if (
      typeof item !== "string" ||
      !/^[A-Za-z0-9]{1,16}$/.test(key) ||
      new TextEncoder().encode(item).length > 200 ||
      normalized.has(folded)
    )
      return INVALID
    normalized.add(folded)
  }
  return value as Record<string, string>
}

function summarizeFields(
  state: MutableKeywordState,
  fields: PatchField[],
  currencyCode: string
): string {
  return fields
    .map((field) => {
      return `${fieldLabel(field)}: ${formatPositiveKeywordValue(field, state[field], currencyCode)}`
    })
    .join(" · ")
}

function fieldLabel(field: PatchField): string {
  return POSITIVE_KEYWORD_PATCH_FIELDS_BY_KEY.get(field)?.label ?? titleCaseToken(field, field)
}

function valuesEqual(
  left: MutableKeywordState[PatchField],
  right: MutableKeywordState[PatchField]
): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}
