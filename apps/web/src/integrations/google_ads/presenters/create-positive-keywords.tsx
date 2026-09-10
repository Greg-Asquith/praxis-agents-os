// apps/web/src/integrations/google_ads/presenters/create-positive-keywords.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import {
  GoogleAdsOutcomeTable,
  type GoogleAdsOutcomeRow,
} from "@/integrations/google_ads/components/outcome-table"
import { outcomeKind, outcomeLabel } from "@/integrations/google_ads/lib/outcomes"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"

import { GoogleAdsApprovalSection } from "@/integrations/google_ads/components/approval-section"
import {
  GoogleAdsEntityCard,
  GoogleAdsEntityGroup,
} from "@/integrations/google_ads/components/entity-card"
import type { GoogleAdsOutcomeColumn as DataColumn } from "@/integrations/google_ads/components/outcome-table"
import { parseAccountCurrencies } from "@/integrations/google_ads/lib/accounts"
import {
  parseAdGroupReference,
  type AdGroupReference,
} from "@/integrations/google_ads/lib/ad-groups"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { parseOutcomeEnvelope } from "@/integrations/google_ads/lib/envelopes"
import { CURRENCY_CODE_PATTERN, googleAdsId } from "@/integrations/google_ads/lib/field-values"
import {
  parsePositiveKeywordInput,
  positiveKeywordInputValidationError,
  type PositiveKeywordInput,
} from "@/integrations/google_ads/lib/positive-keywords"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"
import { formatCurrencyAmount } from "@/lib/format"
import { isNullableString, isRecord } from "@/lib/guards"

const OUTCOMES = ["added", "skipped_existing", "failed", "unverified"] as const

type KeywordOutcome = (typeof OUTCOMES)[number]

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
]

export const googleAdsCreatePositiveKeywordsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_create_keywords: defineIntegrationWriteVariant(googleAdsProvider, {
      copy: { verb: "Add", object: "keywords", effect: "added" },
      approval: {
        parseArgs: createKeywordArgs,
        validateArgs: createKeywordArgsValidationError,
        prompt:
          "Review every ad group, keyword, match type, bid setting, and URL setting before changing live ad delivery.",
        renderSummary: (value) => {
          const parsed = createKeywordArgs(value)
          return parsed ? renderApprovalSummary(parsed) : null
        },
      },
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
      parseResult: createKeywordResult,
      renderFailure: (args, description) => (
        <GoogleAdsFailureTargets
          description={description}
          targets={args?.adGroups.map((item) => item.label) ?? []}
        />
      ),
      renderOutcome: renderOutcome,
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
    <GoogleAdsApprovalSection
      ariaLabel="Proposed keyword additions"
      countLine={`${approvalCountLine(args.keywords.length, "keyword")} × ${approvalCountLine(args.adGroups.length, "ad group")} · ${approvalCountLine(args.adGroups.length * args.keywords.length, "planned addition")}`}
    >
      {[...campaignGroups.entries()].map(([key, adGroups]) => {
        const first = adGroups[0]
        if (!first) return null
        const account = args.accounts.get(first.customerId)
        return (
          <GoogleAdsEntityGroup
            key={key}
            title={first.campaignLabel ?? "Campaign"}
            meta={`${account?.label ?? "Google Ads account"} · ${account?.currencyCode ?? "Currency unavailable"}`}
          >
            {adGroups.map((adGroup) => (
              <GoogleAdsEntityCard
                key={adGroup.adGroupId}
                title={adGroup.label}
                meta="Ad group"
                trailing={approvalCountLine(args.keywords.length, "keyword")}
              />
            ))}
          </GoogleAdsEntityGroup>
        )
      })}
    </GoogleAdsApprovalSection>
  )
}

function renderOutcome(result: CreateKeywordResult) {
  const rows = result.rows.map<GoogleAdsOutcomeRow>((row) => {
    const details = [
      row.message,
      row.observedTruncated ? "Some live URL settings are omitted from this row." : null,
    ]
    return {
      adGroup: row.adGroupName,
      campaign: row.campaignName,
      requestedBids: bidSummary(row.requested, result.currencyCode),
      existingBids: row.observed ? bidSummary(row.observed, result.currencyCode) : "—",
      details: details.filter((value): value is string => Boolean(value)).join(" · "),
      keyword: row.requested.text,
      matchType: googleAdsTokenLabel(row.requested.matchType, row.requested.matchType),
      outcome: row.outcome,
      errorCode: row.errorCode,
      previousState: row.previousState === "existing" ? "Existing keyword" : "Not present",
      requestedStatus: googleAdsTokenLabel(row.requested.status, row.requested.status),
      existingStatus: row.observed
        ? googleAdsTokenLabel(row.observed.status, row.observed.status)
        : "—",
      requestedUrls: urlSummary(row.requested),
      existingUrls: row.observed ? urlSummary(row.observed) : "—",
    }
  })
  return (
    <GoogleAdsOutcomeTable
      columns={RESULT_COLUMNS}
      exportFilename="google-ads-keyword-additions.csv"
      outcomes={OUTCOMES.map((outcome) => ({
        kind: outcomeKind(outcome),
        label: outcomeLabel(outcome),
        count: result.counts[outcome],
      }))}
      rows={rows}
      truncated={result.samplesTruncated}
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
  const accounts = parseAccountCurrencies(value["_account_currencies"])
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
    const parsed = parseAdGroupReference(item)
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

function createKeywordResult(value: unknown): CreateKeywordResult | null {
  if (
    !isRecord(value) ||
    typeof value["currency_code"] !== "string" ||
    !CURRENCY_CODE_PATTERN.test(value["currency_code"])
  )
    return null
  const envelope = parseOutcomeEnvelope(value, OUTCOMES, parseResultRow)
  if (!envelope) return null
  return {
    counts: envelope.counts,
    currencyCode: value["currency_code"],
    rows: envelope.rows,
    samplesTruncated: envelope.truncated,
  }
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
