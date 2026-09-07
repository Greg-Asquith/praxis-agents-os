// apps/web/src/integrations/google_ads/presenters/create-positive-keywords.tsx

import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Stat, StatGroup } from "@/components/ui/stat"
import {
  GOOGLE_ADS_ID_PATTERN,
  parsePositiveKeywordInput,
  positiveKeywordInputValidationError,
  type PositiveKeywordInput,
} from "@/integrations/google_ads/lib/positive-keywords"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"
import { formatCurrencyAmount, titleCaseToken } from "@/lib/format"
import { isNonNegativeInteger, isNullableString, isRecord } from "@/lib/guards"

const OUTCOMES = ["added", "skipped_existing", "failed", "unverified"] as const
const CURRENCY_PATTERN = /^[A-Z]{3}$/

type KeywordOutcome = (typeof OUTCOMES)[number]

type AdGroupReference = {
  adGroupId: string
  campaignId: string
  campaignLabel: string | null
  customerId: string
  label: string
}

type CreateKeywordArgs = {
  accounts: Map<string, { currencyCode: string; label: string }>
  adGroups: AdGroupReference[]
  keywords: PositiveKeywordInput[]
}

type CreateKeywordResultRow = {
  adGroupId: string
  adGroupName: string
  campaignId: string
  campaignName: string
  errorCode: string | null
  externalRef: string | null
  requested: PositiveKeywordInput
  observed: PositiveKeywordInput | null
  observedTruncated: boolean
  message: string | null
  outcome: KeywordOutcome
  previousState: "absent" | "existing"
}

type CreateKeywordResult = {
  counts: Record<KeywordOutcome, number>
  currencyCode: string
  rows: CreateKeywordResultRow[]
  samplesTruncated: boolean
}

const RESULT_COLUMNS: DataColumn[] = [
  { key: "campaign", kind: "text", label: "Campaign" },
  { key: "adGroup", kind: "text", label: "Ad Group" },
  { key: "keyword", kind: "text", label: "Keyword" },
  { key: "matchType", kind: "text", label: "Match Type" },
  { key: "requestedStatus", kind: "status", label: "Requested Status" },
  { key: "existingStatus", kind: "status", label: "Existing Status" },
  { key: "requestedBids", kind: "text", label: "Requested Bid", width: 220 },
  { key: "existingBids", kind: "text", label: "Existing Bid", width: 220 },
  { key: "requestedUrls", kind: "text", label: "Requested URLs", width: 260 },
  { key: "existingUrls", kind: "text", label: "Existing URLs", width: 260 },
  { key: "previousState", kind: "text", label: "Previous State" },
  { key: "outcome", kind: "status", label: "Outcome" },
  { key: "details", kind: "text", label: "Details", width: 280 },
]

export const googleAdsCreatePositiveKeywordsPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-create-positive-keywords",
  variants: {
    google_ads_create_keywords: defineGoogleAdsWriteVariant({
      approval: {
        approveLabel: "Approve & Add",
        label: "Add Google Ads Keywords",
        parseArgs: createKeywordArgs,
        validateArgs: createKeywordArgsValidationError,
        prompt:
          "Review every ad group, keyword, match type, bid setting, and URL setting before changing live ad delivery.",
        renderSummary: (value) => {
          const parsed = createKeywordArgs(value)
          return parsed ? renderApprovalSummary(parsed) : null
        },
        title: "Add Keywords",
      },
      deniedDescription: "This keyword addition was declined. Nothing was added.",
      details: (args) =>
        args
          ? [
              { label: "Ad groups", value: String(args.adGroups.length) },
              { label: "Keyword rows", value: String(args.keywords.length) },
              {
                label: "Planned additions",
                value: String(args.adGroups.length * args.keywords.length),
              },
            ]
          : [],
      emptyLabel: "No Google Ads accounts added keywords.",
      failedDescription: "The update did not finish. No keyword addition was confirmed.",
      heading: "Add Keywords",
      malformedDescription:
        "The system couldn't verify this account's keyword outcomes. Check Google Ads before taking further action.",
      parseResult: createKeywordResult,
      progressLabel: "Adding Google Ads keywords…",
      renderOutcome: renderOutcome,
      resultAriaLabel: "Google Ads positive keyword results",
      resultFailure:
        "The system couldn't verify the keyword additions. Check Google Ads before taking further action.",
      unconfirmedAriaLabel: "Unconfirmed Google Ads keyword addition",
      unverifiedDescription:
        "The system couldn't verify whether Google Ads added these keywords. Check Google Ads before retrying.",
      waitingLabel: "Waiting for keyword approval…",
    }),
  },
})

function renderApprovalSummary(args: CreateKeywordArgs) {
  const campaignGroups = new Map<string, AdGroupReference[]>()
  for (const adGroup of args.adGroups) {
    const key = `${adGroup.customerId}:${adGroup.campaignId}`
    const grouped = campaignGroups.get(key)
    if (grouped) {
      grouped.push(adGroup)
    } else {
      campaignGroups.set(key, [adGroup])
    }
  }
  return (
    <section aria-label="Proposed keyword additions" className="grid gap-3">
      <StatGroup>
        <Stat label="Ad groups" value={args.adGroups.length} />
        <Stat label="Keyword rows" value={args.keywords.length} />
        <Stat label="Planned additions" value={args.adGroups.length * args.keywords.length} />
      </StatGroup>
      <div className="grid gap-2" role="list">
        {[...campaignGroups.entries()].map(([key, adGroups]) => {
          const first = adGroups[0]
          if (!first) return null
          const account = args.accounts.get(first.customerId)
          return (
            <section
              className="border-border min-w-0 overflow-hidden rounded-lg border"
              key={key}
              role="listitem"
            >
              <div className="bg-muted/35 flex min-w-0 items-start justify-between gap-3 px-3 py-2.5">
                <div className="flex min-w-0 flex-col gap-1">
                  <p className="text-muted-foreground text-xs wrap-anywhere">
                    {account?.label ?? "Google Ads account"}
                  </p>
                  {first.campaignLabel ? (
                    <p className="text-sm font-medium wrap-anywhere">{first.campaignLabel}</p>
                  ) : null}
                </div>
                <span className="text-muted-foreground shrink-0 text-xs">
                  {account?.currencyCode ?? "Currency unavailable"}
                </span>
              </div>
              <div className="divide-border border-border divide-y border-t">
                {adGroups.map((adGroup) => (
                  <div
                    className="flex min-w-0 items-start justify-between gap-4 px-3 py-2.5"
                    key={adGroup.adGroupId}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-muted-foreground mb-1 text-xs">Ad group</p>
                      <p className="text-sm leading-relaxed wrap-anywhere">{adGroup.label}</p>
                    </div>
                    <span className="text-muted-foreground shrink-0 text-xs">
                      {args.keywords.length} {args.keywords.length === 1 ? "keyword" : "keywords"}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )
        })}
      </div>
    </section>
  )
}

function renderOutcome(result: CreateKeywordResult) {
  const rows = result.rows.map<DataRow>((row) => {
    const details = [
      row.message,
      row.observedTruncated ? "Some live URL settings are omitted from this row." : null,
    ]
    if (row.errorCode) details.push(titleCaseToken(row.errorCode, row.errorCode))
    return {
      adGroup: row.adGroupName,
      campaign: row.campaignName,
      requestedBids: bidSummary(row.requested, result.currencyCode),
      existingBids: row.observed ? bidSummary(row.observed, result.currencyCode) : "—",
      details: details.filter((value): value is string => Boolean(value)).join(" · ") || "—",
      keyword: row.requested.text,
      matchType: titleCaseToken(row.requested.matchType, row.requested.matchType),
      outcome:
        row.outcome === "skipped_existing"
          ? "Already exists"
          : titleCaseToken(row.outcome, row.outcome),
      previousState: row.previousState === "existing" ? "Existing keyword" : "Not present",
      requestedStatus: titleCaseToken(row.requested.status, row.requested.status),
      existingStatus: row.observed ? titleCaseToken(row.observed.status, row.observed.status) : "—",
      requestedUrls: urlSummary(row.requested),
      existingUrls: row.observed ? urlSummary(row.observed) : "—",
    }
  })
  return (
    <DataTable
      columns={RESULT_COLUMNS}
      exportFilename="google-ads-keyword-additions.csv"
      header={
        <StatGroup className="px-3 pt-2">
          <Stat
            label="Added"
            tone={result.counts.added > 0 ? "success" : undefined}
            value={result.counts.added}
          />
          <Stat label="Already exists" value={result.counts.skipped_existing} />
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
      truncationNote={
        result.samplesTruncated
          ? "The table contains a representative sample. Complete evidence is available in the Audit Log."
          : null
      }
    />
  )
}

function createKeywordArgs(value: unknown): CreateKeywordArgs | null {
  if (!isRecord(value) || !Array.isArray(value["ad_groups"]) || !Array.isArray(value["keywords"]))
    return null
  if (!validArgumentCounts(value["ad_groups"], value["keywords"])) return null
  const adGroups = parseAdGroups(value["ad_groups"])
  const keywords = parseKeywords(value["keywords"])
  if (!adGroups || !keywords || adGroups.length * keywords.length > 2500) return null
  const accounts = parseAccounts(value["_account_currencies"])
  if (!allBidCurrenciesAvailable(adGroups, keywords, accounts)) return null
  return { accounts, adGroups, keywords }
}

function validArgumentCounts(adGroups: unknown[], keywords: unknown[]): boolean {
  return (
    adGroups.length >= 1 && adGroups.length <= 50 && keywords.length >= 1 && keywords.length <= 500
  )
}

function parseAdGroups(values: unknown[]): AdGroupReference[] | null {
  const adGroups: AdGroupReference[] = []
  const identities = new Set<string>()
  for (const item of values) {
    const parsed = parseAdGroup(item)
    if (!parsed) return null
    const identity = `${parsed.customerId}:${parsed.adGroupId}`
    if (identities.has(identity)) return null
    identities.add(identity)
    adGroups.push(parsed)
  }
  return adGroups
}

function parseKeywords(values: unknown[]): PositiveKeywordInput[] | null {
  const keywords: PositiveKeywordInput[] = []
  for (const item of values) {
    const parsed = parsePositiveKeywordInput(item)
    if (!parsed) return null
    keywords.push(parsed)
  }
  return keywords
}

function parseAccounts(value: unknown): Map<string, { currencyCode: string; label: string }> {
  const accounts = new Map<string, { currencyCode: string; label: string }>()
  if (!Array.isArray(value)) return accounts
  for (const item of value) {
    const parsed = parseAccount(item)
    if (parsed) accounts.set(parsed.customerId, parsed.account)
  }
  return accounts
}

function parseAccount(
  value: unknown
): { account: { currencyCode: string; label: string }; customerId: string } | null {
  if (!isRecord(value)) return null
  const customerId = googleAdsId(value["customer_id"])
  const label = value["label"]
  const currencyCode = value["currency_code"]
  if (!customerId || typeof label !== "string" || typeof currencyCode !== "string") return null
  if (!CURRENCY_PATTERN.test(currencyCode)) return null
  return { account: { currencyCode, label }, customerId }
}

function allBidCurrenciesAvailable(
  adGroups: AdGroupReference[],
  keywords: PositiveKeywordInput[],
  accounts: Map<string, unknown>
): boolean {
  if (!keywords.some((keyword) => keyword.cpcBid !== null)) return true
  return adGroups.every((adGroup) => accounts.has(adGroup.customerId))
}

function createKeywordArgsValidationError(value: unknown): string | null {
  if (!isRecord(value) || !Array.isArray(value["keywords"])) return null
  for (const keyword of value["keywords"]) {
    const error = positiveKeywordInputValidationError(keyword)
    if (error) return error
  }
  return null
}

function parseAdGroup(value: unknown): AdGroupReference | null {
  if (!isRecord(value)) return null
  if (!isExpectedEntityKind(value["entity_kind"], "google_ads_ad_group")) return null
  const customerId = googleAdsId(value["customer_id"])
  const campaignId = googleAdsId(value["campaign_id"])
  const adGroupId = googleAdsId(value["ad_group_id"])
  if (!customerId || !campaignId) return null
  if (!adGroupId || typeof value["label"] !== "string") return null
  return {
    adGroupId,
    campaignId,
    campaignLabel:
      typeof value["scope_label"] === "string" && value["scope_label"].trim()
        ? value["scope_label"]
        : null,
    customerId,
    label: value["label"].trim() || adGroupId,
  }
}

function isExpectedEntityKind(value: unknown, expected: string): boolean {
  return value == null || value === expected
}

function googleAdsId(value: unknown): string | null {
  return typeof value === "string" && GOOGLE_ADS_ID_PATTERN.test(value) ? value : null
}

function createKeywordResult(value: unknown): CreateKeywordResult | null {
  if (!isResultEnvelope(value)) return null
  const counts = {} as Record<KeywordOutcome, number>
  const rows: CreateKeywordResultRow[] = []
  for (const outcome of OUTCOMES) {
    const count = value.counts[outcome]
    const samples = value.samples[outcome]
    if (!isNonNegativeInteger(count) || !Array.isArray(samples)) return null
    counts[outcome] = count
    for (const sample of samples) {
      const row = parseResultRow(sample, outcome)
      if (!row) return null
      rows.push(row)
    }
  }
  if (
    !value.samples_truncated &&
    rows.length !== OUTCOMES.reduce((total, outcome) => total + counts[outcome], 0)
  )
    return null
  return {
    counts,
    currencyCode: value.currency_code,
    rows,
    samplesTruncated: value.samples_truncated,
  }
}

function isResultEnvelope(value: unknown): value is Record<string, unknown> & {
  currency_code: string
  counts: Record<string, unknown>
  samples: Record<string, unknown>
  samples_truncated: boolean
} {
  if (!isRecord(value) || !isRecord(value["counts"]) || !isRecord(value["samples"])) return false
  if (typeof value["currency_code"] !== "string") return false
  if (!CURRENCY_PATTERN.test(value["currency_code"])) return false
  return typeof value["samples_truncated"] === "boolean"
}

function parseResultRow(value: unknown, outcome: KeywordOutcome): CreateKeywordResultRow | null {
  if (!isRecord(value)) return null
  const state = resultRowState(value, outcome)
  if (!state) return null
  const identity = resultRowIdentity(value)
  const diagnostics = resultRowDiagnostics(value)
  if (!identity || !diagnostics) return null
  return { ...identity, ...diagnostics, ...state }
}

function resultRowState(
  value: Record<string, unknown>,
  outcome: KeywordOutcome
): Pick<
  CreateKeywordResultRow,
  "observed" | "observedTruncated" | "outcome" | "previousState" | "requested"
> | null {
  const requested = parsePositiveKeywordInput(value["requested"])
  const observed = parseObservedKeyword(value["observed"])
  if (value["outcome"] !== outcome || requested === null) return null
  if (observed === undefined) return null
  const truncated = value["observed_truncated"]
  if (truncated !== undefined && typeof truncated !== "boolean") return null
  const previousState = value["previous_state"]
  if (previousState !== "absent" && previousState !== "existing") return null
  return {
    requested,
    observed,
    observedTruncated: truncated ?? false,
    outcome,
    previousState,
  }
}

function parseObservedKeyword(value: unknown): PositiveKeywordInput | null | undefined {
  if (value == null) return null
  return parsePositiveKeywordInput(value) ?? undefined
}

function resultRowIdentity(
  value: Record<string, unknown>
): Pick<
  CreateKeywordResultRow,
  "adGroupId" | "adGroupName" | "campaignId" | "campaignName"
> | null {
  const campaignId = googleAdsId(value["campaign_id"])
  const adGroupId = googleAdsId(value["ad_group_id"])
  if (!campaignId || !adGroupId) return null
  if (typeof value["campaign_name"] !== "string" || typeof value["ad_group_name"] !== "string")
    return null
  return {
    adGroupId,
    adGroupName: value["ad_group_name"],
    campaignId,
    campaignName: value["campaign_name"],
  }
}

function resultRowDiagnostics(
  value: Record<string, unknown>
): Pick<CreateKeywordResultRow, "errorCode" | "externalRef" | "message"> | null {
  const errorCode = value["error_code"]
  const externalRef = value["external_ref"]
  const message = value["message"]
  if (errorCode !== undefined && !isNullableString(errorCode)) return null
  if (externalRef !== undefined && !isNullableString(externalRef)) return null
  if (message !== undefined && !isNullableString(message)) return null
  return {
    errorCode: errorCode ?? null,
    externalRef: externalRef ?? null,
    message: message ?? null,
  }
}

function bidSummary(
  keyword: Pick<PositiveKeywordInput, "bidModifier" | "cpcBid">,
  currencyCode: string
): string {
  const bids = [
    keyword.cpcBid ? `CPC ${formatCurrencyAmount(keyword.cpcBid, currencyCode)}` : null,
    keyword.bidModifier === null ? null : `Adjustment ${String(keyword.bidModifier)}×`,
  ].filter((value): value is string => value !== null)
  return bids.length > 0 ? bids.join(" · ") : "Ad group default"
}

function urlSummary(
  keyword: Pick<
    PositiveKeywordInput,
    | "finalUrls"
    | "finalMobileUrls"
    | "finalUrlSuffix"
    | "trackingUrlTemplate"
    | "urlCustomParameters"
  >
): string {
  const values = [
    ...keyword.finalUrls.map((url) => `Final: ${url}`),
    ...keyword.finalMobileUrls.map((url) => `Mobile: ${url}`),
    keyword.finalUrlSuffix ? `Suffix: ${keyword.finalUrlSuffix}` : null,
    keyword.trackingUrlTemplate ? `Tracking: ${keyword.trackingUrlTemplate}` : null,
    ...Object.entries(keyword.urlCustomParameters).map(([key, value]) => `{_${key}}=${value}`),
  ].filter((value): value is string => value !== null)
  return values.join(" · ") || "None"
}
