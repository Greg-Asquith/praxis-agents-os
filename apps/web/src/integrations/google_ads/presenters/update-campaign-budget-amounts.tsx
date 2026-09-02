// apps/web/src/integrations/google_ads/presenters/update-campaign-budget-amounts.tsx

import { ArrowRightIcon } from "lucide-react"

import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Stat, StatGroup } from "@/components/ui/stat"
import {
  budgetPeriodLabel,
  campaignBudgetIdentity,
  formatCampaignBudgetAmount,
  formatDailyEstimate,
  linkedCampaignLabel,
  parseCampaignBudgetReference,
  type CampaignBudgetWithCurrency,
} from "@/integrations/google_ads/lib/campaign-budgets"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"
import { formatCurrencyAmount, formatPercentageChange, titleCaseToken } from "@/lib/format"
import { isNullableString, isRecord, parsePositiveDecimal } from "@/lib/guards"

const OUTCOMES = ["updated", "already_set", "failed", "unverified"] as const
type BudgetAmountOutcome = (typeof OUTCOMES)[number]

type BudgetAmountUpdate = {
  amount: string
  budget: CampaignBudgetWithCurrency
}

type UpdateBudgetArgs = {
  updates: BudgetAmountUpdate[]
}

type BudgetAmountResult = {
  campaignLabelCount: number
  campaignLabelsTruncated: boolean
  errorCode: string | null
  message: string | null
  outcome: BudgetAmountOutcome
  previousAmount: string
  reference: CampaignBudgetWithCurrency
  requestedAmount: string
}

type UpdateBudgetResult = {
  campaignLabelsTruncated: boolean
  counts: Record<BudgetAmountOutcome, number>
  rows: BudgetAmountResult[]
  samplesTruncated: boolean
}

const COLUMNS: DataColumn[] = [
  { key: "budget", kind: "text", label: "Budget" },
  { key: "previous", kind: "text", label: "Before", align: "right" },
  { key: "requested", kind: "text", label: "After", align: "right" },
  { key: "change", kind: "text", label: "Change", width: 180 },
  { key: "period", kind: "text", label: "Period" },
  { key: "linkedCampaigns", kind: "text", label: "Linked Campaigns" },
  { key: "outcome", kind: "status", label: "Outcome" },
  { key: "details", kind: "text", label: "Details" },
]

export const googleAdsUpdateCampaignBudgetAmountsPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-update-campaign-budget-amounts",
  variants: {
    google_ads_update_campaign_budget_amounts: defineGoogleAdsWriteVariant({
      approval: {
        approveLabel: "Approve & Update",
        label: "Update Google Ads Campaign Budget Amounts",
        parseArgs: updateBudgetArgs,
        prompt: "Review each selected budget amount before changing live spend limits.",
        renderSummary: (value, fallback) =>
          renderUpdateBudgetApprovalSummary(updateBudgetArgs(value) ?? fallback),
        title: "Update Campaign Budget Amounts",
      },
      deniedDescription: "This campaign budget update was declined. Nothing was changed.",
      details: (args) => (args ? [{ label: "Budgets", value: String(args.updates.length) }] : []),
      emptyLabel: "No Google Ads accounts updated campaign budget amounts.",
      failedDescription: "The update did not finish. No campaign budget change was confirmed.",
      heading: "Update Campaign Budget Amounts",
      malformedDescription:
        "The system couldn't verify this account's campaign budget amount outcomes. Check Google Ads before taking further action.",
      parseResult: updateBudgetResult,
      progressLabel: "Updating Google Ads campaign budget amounts…",
      renderOutcome: renderUpdateBudgetOutcome,
      resultAriaLabel: "Google Ads campaign budget amount results",
      resultFailure:
        "The system couldn't verify the campaign budget amount changes. Check Google Ads before taking further action.",
      unconfirmedAriaLabel: "Unconfirmed Google Ads campaign budget amount update",
      unverifiedDescription:
        "The system couldn't verify whether Google Ads applied these campaign budget amount changes. Check Google Ads before retrying.",
      waitingLabel: "Waiting for campaign budget approval…",
    }),
  },
})

function renderUpdateBudgetApprovalSummary(args: UpdateBudgetArgs) {
  return (
    <section aria-label="Proposed campaign budget amounts" className="grid gap-1.5">
      {args.updates.map((update) => (
        <div
          className="border-border/80 bg-card grid min-w-0 gap-3 rounded-lg border px-3 py-3 shadow-xs sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
          key={`${campaignBudgetIdentity(update.budget)}:${update.amount}`}
        >
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{update.budget.label}</p>
            <p className="text-muted-foreground mt-0.5 text-xs">
              {budgetPeriodLabel(update.budget.period)} ·{" "}
              {linkedCampaignLabel(update.budget.referenceCount)}
            </p>
          </div>
          <div
            aria-label={`${formatCampaignBudgetAmount(update.budget)} before, ${formatCurrencyAmount(update.amount, update.budget.currencyCode)} after`}
            className="border-border bg-muted/25 grid grid-cols-[minmax(5rem,1fr)_auto_minmax(5rem,1fr)] items-center gap-2 rounded-md border px-3 py-2 tabular-nums sm:min-w-64"
          >
            <div>
              <p className="text-muted-foreground text-[11px] leading-none">Current</p>
              <p className="mt-1 text-sm font-medium">
                {formatCampaignBudgetAmount(update.budget)}
              </p>
            </div>
            <span className="bg-background text-muted-foreground flex size-6 items-center justify-center rounded-full border">
              <ArrowRightIcon aria-hidden="true" className="size-3.5" />
            </span>
            <div className="text-right">
              <p className="text-muted-foreground text-[11px] leading-none">Proposed</p>
              <p className="mt-1 text-sm font-semibold">
                {formatCurrencyAmount(update.amount, update.budget.currencyCode)}
              </p>
            </div>
          </div>
        </div>
      ))}
    </section>
  )
}

function renderUpdateBudgetOutcome(result: UpdateBudgetResult) {
  const rows = result.rows.map<DataRow>((row) => {
    const details = [row.message]
    if (row.errorCode) {
      details.push(titleCaseToken(row.errorCode, row.errorCode))
    }
    if (row.reference.period === "DAILY") {
      details.push(formatDailyEstimate(row.requestedAmount, row.reference.currencyCode))
    }
    return {
      budget: row.reference.label,
      change: formatPercentageChange(Number(row.previousAmount), Number(row.requestedAmount)),
      details: details.filter((value): value is string => Boolean(value)).join(" · ") || "—",
      linkedCampaigns: linkedCampaignLabel(row.reference.referenceCount ?? row.campaignLabelCount),
      outcome:
        row.outcome === "already_set" ? "Already set" : titleCaseToken(row.outcome, row.outcome),
      period: budgetPeriodLabel(row.reference.period),
      previous: formatCurrencyAmount(row.previousAmount, row.reference.currencyCode),
      previousRaw: row.previousAmount,
      requested: formatCurrencyAmount(row.requestedAmount, row.reference.currencyCode),
      requestedRaw: row.requestedAmount,
    }
  })
  const note = result.samplesTruncated
    ? "The table contains a representative sample. Complete evidence is available in the Audit Log."
    : result.campaignLabelsTruncated
      ? "Some linked campaign names are omitted from the retained result."
      : null
  return (
    <DataTable
      columns={COLUMNS}
      exportFilename="campaign-budget-amounts.csv"
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
      renderCell={renderBudgetChangeCell}
      rows={rows}
      truncationNote={note}
    />
  )
}

function renderBudgetChangeCell(column: DataColumn, row: DataRow) {
  if (column.key !== "change") {
    return null
  }
  const previous = Number(row["previousRaw"])
  const requested = Number(row["requestedRaw"])
  const change = typeof row["change"] === "string" ? row["change"] : "—"
  if (!Number.isFinite(previous) || !Number.isFinite(requested) || previous <= 0) {
    return <span>{change}</span>
  }
  const maximum = Math.max(previous, requested)
  return (
    <div aria-label={`${change} from the previous amount`} className="grid gap-1">
      <div className="bg-muted h-1.5 overflow-hidden rounded-full">
        <div
          className="bg-muted-foreground/45 h-full rounded-full"
          style={{ width: `${String(Math.max(3, (previous / maximum) * 100))}%` }}
        />
      </div>
      <div className="bg-muted h-1.5 overflow-hidden rounded-full">
        <div
          className={
            requested >= previous
              ? "bg-success h-full rounded-full"
              : "bg-warning h-full rounded-full"
          }
          style={{ width: `${String(Math.max(3, (requested / maximum) * 100))}%` }}
        />
      </div>
      <span className="text-muted-foreground text-xs tabular-nums">{change}</span>
    </div>
  )
}

function updateBudgetArgs(value: unknown): UpdateBudgetArgs | null {
  if (!isRecord(value) || !Array.isArray(value["updates"]) || value["updates"].length === 0) {
    return null
  }
  const updates: BudgetAmountUpdate[] = []
  const identities = new Set<string>()
  for (const item of value["updates"]) {
    if (!isRecord(item)) {
      return null
    }
    const budget = parseCampaignBudgetReference(item["budget"])
    const amount = parsePositiveDecimal(item["amount"])
    const identity = budget ? campaignBudgetIdentity(budget) : null
    const currentAmountAvailable =
      budget?.period === "DAILY"
        ? budget.amountMicros !== null
        : budget?.period === "CUSTOM_PERIOD"
          ? budget.totalAmountMicros !== null
          : false
    if (
      !budget?.currencyCode ||
      !amount ||
      identity === null ||
      !currentAmountAvailable ||
      identities.has(identity)
    ) {
      return null
    }
    identities.add(identity)
    updates.push({ amount, budget: { ...budget, currencyCode: budget.currencyCode } })
  }
  return { updates }
}

function updateBudgetResult(value: unknown): UpdateBudgetResult | null {
  if (
    !isRecord(value) ||
    !isRecord(value["counts"]) ||
    !isRecord(value["samples"]) ||
    typeof value["samples_truncated"] !== "boolean" ||
    typeof value["campaign_labels_truncated"] !== "boolean"
  ) {
    return null
  }
  const counts = {} as Record<BudgetAmountOutcome, number>
  for (const outcome of OUTCOMES) {
    const count = value["counts"][outcome]
    if (typeof count !== "number" || !Number.isSafeInteger(count) || count < 0) {
      return null
    }
    counts[outcome] = count
  }
  const rows: BudgetAmountResult[] = []
  for (const outcome of OUTCOMES) {
    const samples = value["samples"][outcome]
    if (!Array.isArray(samples)) {
      return null
    }
    for (const sample of samples) {
      const row = budgetAmountRow(sample, outcome)
      if (!row) {
        return null
      }
      rows.push(row)
    }
  }
  if (
    !value["samples_truncated"] &&
    rows.length !== OUTCOMES.reduce((total, outcome) => total + counts[outcome], 0)
  ) {
    return null
  }
  return {
    campaignLabelsTruncated: value["campaign_labels_truncated"],
    counts,
    rows,
    samplesTruncated: value["samples_truncated"],
  }
}

function budgetAmountRow(
  value: unknown,
  expectedOutcome: BudgetAmountOutcome
): BudgetAmountResult | null {
  if (
    !isRecord(value) ||
    value["outcome"] !== expectedOutcome ||
    typeof value["campaign_label_count"] !== "number" ||
    !Number.isSafeInteger(value["campaign_label_count"]) ||
    value["campaign_label_count"] < 0 ||
    typeof value["campaign_labels_truncated"] !== "boolean"
  ) {
    return null
  }
  const reference = parseCampaignBudgetReference(value["reference"])
  const previousAmount = parsePositiveDecimal(value["previous_amount"])
  const requestedAmount = parsePositiveDecimal(value["requested_amount"])
  if (
    !reference?.currencyCode ||
    !previousAmount ||
    !requestedAmount ||
    !isNullableString(value["error_code"] ?? null) ||
    !isNullableString(value["message"] ?? null)
  ) {
    return null
  }
  return {
    campaignLabelCount: value["campaign_label_count"],
    campaignLabelsTruncated: value["campaign_labels_truncated"],
    errorCode: typeof value["error_code"] === "string" ? value["error_code"] : null,
    message: typeof value["message"] === "string" ? value["message"] : null,
    outcome: expectedOutcome,
    previousAmount,
    reference: { ...reference, currencyCode: reference.currencyCode },
    requestedAmount,
  }
}
