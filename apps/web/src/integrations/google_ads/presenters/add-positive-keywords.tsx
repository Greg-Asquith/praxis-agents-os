// apps/web/src/integrations/google_ads/presenters/add-positive-keywords.tsx

import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Stat, StatGroup } from "@/components/ui/stat"
import {
  GOOGLE_ADS_ID_PATTERN,
  parsePositiveKeywordInput,
  POSITIVE_KEYWORD_MATCH_TYPES,
  type PositiveKeywordInput,
  type PositiveKeywordMatchType,
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
  campaignLabel: string
  customerId: string
  label: string
}

type AddKeywordArgs = {
  accounts: Map<string, { currencyCode: string; label: string }>
  adGroups: AdGroupReference[]
  keywords: PositiveKeywordInput[]
}

type AddKeywordResultRow = {
  adGroupId: string
  adGroupName: string
  campaignId: string
  campaignName: string
  cpcBid: string | null
  errorCode: string | null
  externalRef: string | null
  matchType: PositiveKeywordMatchType
  message: string | null
  outcome: KeywordOutcome
  previousState: "absent" | "existing"
  text: string
}

type AddKeywordResult = {
  counts: Record<KeywordOutcome, number>
  currencyCode: string
  rows: AddKeywordResultRow[]
  samplesTruncated: boolean
}

const RESULT_COLUMNS: DataColumn[] = [
  { key: "campaign", kind: "text", label: "Campaign" },
  { key: "adGroup", kind: "text", label: "Ad Group" },
  { key: "keyword", kind: "text", label: "Keyword" },
  { key: "matchType", kind: "text", label: "Match Type" },
  { key: "cpcBid", kind: "text", label: "CPC Bid" },
  { key: "previousState", kind: "text", label: "Previous State" },
  { key: "outcome", kind: "status", label: "Outcome" },
  { key: "details", kind: "text", label: "Details", width: 280 },
]

export const googleAdsAddPositiveKeywordsPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-add-positive-keywords",
  variants: {
    google_ads_add_keywords: defineGoogleAdsWriteVariant({
      approval: {
        approveLabel: "Approve & Add",
        label: "Add Google Ads Keywords",
        parseArgs: addKeywordArgs,
        prompt:
          "Review every ad group, keyword, match type, and optional CPC bid before changing live ad delivery.",
        renderSummary: (value) => {
          const parsed = addKeywordArgs(value)
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
      parseResult: addKeywordResult,
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

function renderApprovalSummary(args: AddKeywordArgs) {
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
              className="border-border bg-muted/35 rounded-lg border px-3 py-2.5"
              key={key}
              role="listitem"
            >
              <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-2">
                <p className="truncate text-sm font-semibold">{first.campaignLabel}</p>
                <p className="text-muted-foreground text-xs">
                  {account?.label ?? "Google Ads account"} ·{" "}
                  {account?.currencyCode ?? "Currency unavailable"}
                </p>
              </div>
              <div className="mt-2 grid gap-1">
                {adGroups.map((adGroup) => (
                  <div
                    className="bg-card flex min-w-0 items-center justify-between gap-3 rounded-md border px-2.5 py-2 text-sm"
                    key={adGroup.adGroupId}
                  >
                    <span className="truncate font-medium">{adGroup.label}</span>
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

function renderOutcome(result: AddKeywordResult) {
  const rows = result.rows.map<DataRow>((row) => {
    const details = [row.message]
    if (row.errorCode) details.push(titleCaseToken(row.errorCode, row.errorCode))
    return {
      adGroup: row.adGroupName,
      campaign: row.campaignName,
      cpcBid: row.cpcBid
        ? formatCurrencyAmount(row.cpcBid, result.currencyCode)
        : "Ad group default",
      details: details.filter((value): value is string => Boolean(value)).join(" · ") || "—",
      keyword: row.text,
      matchType: titleCaseToken(row.matchType, row.matchType),
      outcome:
        row.outcome === "skipped_existing"
          ? "Already exists"
          : titleCaseToken(row.outcome, row.outcome),
      previousState: row.previousState === "existing" ? "Existing keyword" : "Not present",
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

function addKeywordArgs(value: unknown): AddKeywordArgs | null {
  if (!isRecord(value) || !Array.isArray(value["ad_groups"]) || !Array.isArray(value["keywords"]))
    return null
  if (
    value["ad_groups"].length < 1 ||
    value["ad_groups"].length > 50 ||
    value["keywords"].length < 1 ||
    value["keywords"].length > 500
  )
    return null
  const adGroups: AdGroupReference[] = []
  const identities = new Set<string>()
  for (const item of value["ad_groups"]) {
    const parsed = parseAdGroup(item)
    if (!parsed) return null
    const identity = `${parsed.customerId}:${parsed.adGroupId}`
    if (identities.has(identity)) return null
    identities.add(identity)
    adGroups.push(parsed)
  }
  const keywords: PositiveKeywordInput[] = []
  const keywordKeys = new Set<string>()
  for (const item of value["keywords"]) {
    const parsed = parsePositiveKeywordInput(item)
    if (!parsed) return null
    const identity = `${parsed.text.toLowerCase()}:${parsed.matchType}`
    if (keywordKeys.has(identity)) return null
    keywordKeys.add(identity)
    keywords.push(parsed)
  }
  if (adGroups.length * keywords.length > 2500) return null
  const accounts = new Map<string, { currencyCode: string; label: string }>()
  if (Array.isArray(value["_account_currencies"])) {
    for (const item of value["_account_currencies"]) {
      if (
        isRecord(item) &&
        typeof item["customer_id"] === "string" &&
        GOOGLE_ADS_ID_PATTERN.test(item["customer_id"]) &&
        typeof item["label"] === "string" &&
        typeof item["currency_code"] === "string" &&
        CURRENCY_PATTERN.test(item["currency_code"])
      ) {
        accounts.set(item["customer_id"], {
          currencyCode: item["currency_code"],
          label: item["label"],
        })
      }
    }
  }
  if (keywords.some((keyword) => keyword.cpcBid !== null)) {
    const customerIds = new Set(adGroups.map((adGroup) => adGroup.customerId))
    if ([...customerIds].some((customerId) => !accounts.has(customerId))) return null
  }
  return { accounts, adGroups, keywords }
}

function parseAdGroup(value: unknown): AdGroupReference | null {
  if (
    !isRecord(value) ||
    (value["entity_kind"] != null && value["entity_kind"] !== "google_ads_ad_group") ||
    typeof value["customer_id"] !== "string" ||
    !GOOGLE_ADS_ID_PATTERN.test(value["customer_id"]) ||
    typeof value["campaign_id"] !== "string" ||
    !GOOGLE_ADS_ID_PATTERN.test(value["campaign_id"]) ||
    typeof value["ad_group_id"] !== "string" ||
    !GOOGLE_ADS_ID_PATTERN.test(value["ad_group_id"]) ||
    typeof value["label"] !== "string"
  )
    return null
  return {
    adGroupId: value["ad_group_id"],
    campaignId: value["campaign_id"],
    campaignLabel:
      typeof value["scope_label"] === "string" && value["scope_label"].trim()
        ? value["scope_label"]
        : "Campaign",
    customerId: value["customer_id"],
    label: value["label"].trim() || value["ad_group_id"],
  }
}

function addKeywordResult(value: unknown): AddKeywordResult | null {
  if (
    !isRecord(value) ||
    typeof value["currency_code"] !== "string" ||
    !CURRENCY_PATTERN.test(value["currency_code"]) ||
    !isRecord(value["counts"]) ||
    !isRecord(value["samples"]) ||
    typeof value["samples_truncated"] !== "boolean"
  )
    return null
  const counts = {} as Record<KeywordOutcome, number>
  const rows: AddKeywordResultRow[] = []
  for (const outcome of OUTCOMES) {
    const count = value["counts"][outcome]
    const samples = value["samples"][outcome]
    if (!isNonNegativeInteger(count) || !Array.isArray(samples)) return null
    counts[outcome] = count
    for (const sample of samples) {
      const row = parseResultRow(sample, outcome)
      if (!row) return null
      rows.push(row)
    }
  }
  if (
    !value["samples_truncated"] &&
    rows.length !== OUTCOMES.reduce((total, outcome) => total + counts[outcome], 0)
  )
    return null
  return {
    counts,
    currencyCode: value["currency_code"],
    rows,
    samplesTruncated: value["samples_truncated"],
  }
}

function parseResultRow(value: unknown, outcome: KeywordOutcome): AddKeywordResultRow | null {
  if (
    !isRecord(value) ||
    value["outcome"] !== outcome ||
    typeof value["text"] !== "string" ||
    typeof value["match_type"] !== "string" ||
    !POSITIVE_KEYWORD_MATCH_TYPES.has(value["match_type"] as PositiveKeywordMatchType) ||
    (value["previous_state"] !== "absent" && value["previous_state"] !== "existing") ||
    (value["cpc_bid"] !== undefined && !isNullableString(value["cpc_bid"])) ||
    (value["external_ref"] !== undefined && !isNullableString(value["external_ref"])) ||
    (value["error_code"] !== undefined && !isNullableString(value["error_code"])) ||
    (value["message"] !== undefined && !isNullableString(value["message"]))
  )
    return null
  if (
    typeof value["campaign_id"] !== "string" ||
    !GOOGLE_ADS_ID_PATTERN.test(value["campaign_id"]) ||
    typeof value["campaign_name"] !== "string" ||
    typeof value["ad_group_id"] !== "string" ||
    !GOOGLE_ADS_ID_PATTERN.test(value["ad_group_id"]) ||
    typeof value["ad_group_name"] !== "string"
  )
    return null
  return {
    adGroupId: value["ad_group_id"],
    adGroupName: value["ad_group_name"],
    campaignId: value["campaign_id"],
    campaignName: value["campaign_name"],
    cpcBid: value["cpc_bid"] ?? null,
    errorCode: value["error_code"] ?? null,
    externalRef: value["external_ref"] ?? null,
    matchType: value["match_type"] as PositiveKeywordMatchType,
    message: value["message"] ?? null,
    outcome,
    previousState: value["previous_state"],
    text: value["text"],
  }
}
