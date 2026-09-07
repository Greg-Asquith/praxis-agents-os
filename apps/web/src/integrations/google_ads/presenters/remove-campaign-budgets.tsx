// apps/web/src/integrations/google_ads/presenters/remove-campaing-budgets.tsx

import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Stat, StatGroup } from "@/components/ui/stat"
import {
  budgetPeriodLabel,
  formatCampaignBudgetAmount,
  campaignBudgetIdentity,
  parseCampaignBudgetReference,
  type CampaignBudgetWithCurrency,
} from "@/integrations/google_ads/lib/campaign-budgets"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"
import { titleCaseToken } from "@/lib/format"

import { isNonNegativeInteger, isNullableString, isRecord } from "@/lib/guards"

const OUTCOMES = ["removed", "failed", "unverified"] as const
type RemovalOutcome = (typeof OUTCOMES)[number]

type RemovalArgs = {
  budgets: CampaignBudgetWithCurrency[]
}

type RemovalResultRow = {
  errorCode: string | null
  message: string | null
  outcome: RemovalOutcome
  previousStatus: string
  reference: CampaignBudgetWithCurrency
  resultingStatus: string | null
}

type RemovalResult = {
  counts: Record<RemovalOutcome, number>
  rows: RemovalResultRow[]
  samplesTruncated: boolean
}

const COLUMNS: DataColumn[] = [
  { key: "budget", kind: "text", label: "Budget" },
  { key: "budgetId", kind: "id", label: "Budget ID" },
  { key: "amount", kind: "text", label: "Amount", align: "right" },
  { key: "period", kind: "text", label: "Period" },
  { key: "linkedCampaigns", kind: "text", label: "Linked Campaigns" },
  { key: "previousStatus", kind: "status", label: "Before" },
  { key: "resultingStatus", kind: "status", label: "After" },
  { key: "outcome", kind: "status", label: "Outcome" },
  { key: "details", kind: "text", label: "Details" },
]

export const googleAdsRemoveCampaignBudgetsPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-remove-campaign-budgets",
  variants: {
    google_ads_remove_campaign_budgets: defineGoogleAdsWriteVariant({
      approval: {
        approveLabel: "Approve & Remove",
        label: "Remove Google Ads Campaign Budgets",
        parseArgs: removalArgs,
        prompt: "These unused campaign budgets are permanently removed from Google Ads.",
        renderSummary: (value, fallback) =>
          renderRemovalApprovalSummary(removalArgs(value) ?? fallback),
        title: "Permanently Remove Campaign Budgets",
      },
      deniedDescription: "This campaign budget removal was declined. Nothing was removed.",
      details: (args) => (args ? [{ label: "Budgets", value: String(args.budgets.length) }] : []),
      emptyLabel: "No Google Ads accounts removed campaign budgets.",
      failedDescription: "The removal did not finish. No campaign budget removal was confirmed.",
      heading: "Remove Campaign Budgets",
      malformedDescription:
        "The system couldn't verify this account's campaign budget removal outcomes. Check Google Ads before taking further action.",
      parseResult: removalResult,
      progressLabel: "Removing Google Ads campaign budgets…",
      renderOutcome: renderRemovalOutcomeTable,
      resultAriaLabel: "Google Ads campaign budget removal results",
      resultFailure:
        "The system couldn't verify the campaign budget removals. Check Google Ads before taking further action.",
      unconfirmedAriaLabel: "Unconfirmed Google Ads campaign budget removal",
      unverifiedDescription:
        "The system couldn't verify whether Google Ads removed these campaign budgets. Check Google Ads before retrying.",
      waitingLabel: "Waiting for campaign budget removal approval…",
    }),
  },
})

function renderRemovalApprovalSummary(args: RemovalArgs) {
  return (
    <section
      aria-label="Campaign budgets selected for permanent removal"
      className="border-destructive/35 bg-destructive/5 grid gap-2 rounded-lg border px-3 py-2.5"
    >
      <p className="text-destructive text-xs font-medium">
        This action cannot be undone. Each budget has zero linked campaigns.
      </p>
      <div className="grid gap-1" role="list">
        {args.budgets.map((budget) => (
          <div
            className="bg-card flex min-w-0 flex-wrap items-baseline justify-between gap-2 rounded-md border px-2.5 py-2"
            key={campaignBudgetIdentity(budget)}
            role="listitem"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{budget.label}</p>
              <p className="text-muted-foreground text-xs">
                {budgetPeriodLabel(budget.period)} ·{" "}
                {budget.referenceCount === null
                  ? "Unavailable"
                  : approvalCountLine(budget.referenceCount, "campaign")}
              </p>
            </div>
            <p className="text-sm font-semibold tabular-nums">
              {formatCampaignBudgetAmount(budget)}
            </p>
          </div>
        ))}
      </div>
    </section>
  )
}

function renderRemovalOutcomeTable(result: RemovalResult) {
  const rows = result.rows.map<DataRow>((row) => {
    const details = [row.message]
    if (row.errorCode) {
      details.push(titleCaseToken(row.errorCode, row.errorCode))
    }
    return {
      amount: formatCampaignBudgetAmount(row.reference),
      budget: row.reference.label,
      budgetId: row.reference.budgetId,
      details: details.filter((value): value is string => Boolean(value)).join(" · ") || "—",
      linkedCampaigns:
        row.reference.referenceCount === null
          ? "Unavailable"
          : approvalCountLine(row.reference.referenceCount, "campaign"),
      outcome: titleCaseToken(row.outcome, row.outcome),
      period: budgetPeriodLabel(row.reference.period),
      previousStatus: titleCaseToken(row.previousStatus, row.previousStatus),
      resultingStatus:
        row.resultingStatus === null
          ? "Unverified"
          : titleCaseToken(row.resultingStatus, row.resultingStatus),
    }
  })
  return (
    <DataTable
      columns={COLUMNS}
      exportFilename="removed-campaign-budgets.csv"
      header={
        <StatGroup className="px-3 pt-2">
          <Stat
            label="Removed"
            tone={result.counts.removed > 0 ? "success" : undefined}
            value={result.counts.removed}
          />
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

function removalArgs(value: unknown): RemovalArgs | null {
  if (!isRecord(value) || !Array.isArray(value["budgets"]) || value["budgets"].length === 0) {
    return null
  }
  const budgets: CampaignBudgetWithCurrency[] = []
  const budgetIds = new Set<string>()
  for (const valueBudget of value["budgets"]) {
    const budget = parseCampaignBudgetReference(valueBudget)
    const identity = budget ? campaignBudgetIdentity(budget) : null
    if (
      !budget?.currencyCode ||
      budget.referenceCount !== 0 ||
      identity === null ||
      budgetIds.has(identity)
    ) {
      return null
    }
    budgetIds.add(identity)
    budgets.push({ ...budget, currencyCode: budget.currencyCode })
  }
  return { budgets }
}

function removalResult(value: unknown): RemovalResult | null {
  if (
    !isRecord(value) ||
    !isRecord(value["counts"]) ||
    !isRecord(value["samples"]) ||
    typeof value["samples_truncated"] !== "boolean"
  ) {
    return null
  }
  const counts = value["counts"]
  if (
    !isNonNegativeInteger(counts["removed"]) ||
    !isNonNegativeInteger(counts["failed"]) ||
    !isNonNegativeInteger(counts["unverified"])
  ) {
    return null
  }
  const rows: RemovalResultRow[] = []
  for (const outcome of OUTCOMES) {
    const samples = value["samples"][outcome]
    if (!Array.isArray(samples)) {
      return null
    }
    for (const sample of samples) {
      if (
        !isRecord(sample) ||
        sample["outcome"] !== outcome ||
        typeof sample["previous_status"] !== "string" ||
        !isNullableString(sample["resulting_status"] ?? null) ||
        !isNullableString(sample["error_code"] ?? null) ||
        !isNullableString(sample["message"] ?? null)
      ) {
        return null
      }
      const reference = parseCampaignBudgetReference(sample["reference"])
      if (!reference?.currencyCode) {
        return null
      }
      rows.push({
        errorCode: typeof sample["error_code"] === "string" ? sample["error_code"] : null,
        message: typeof sample["message"] === "string" ? sample["message"] : null,
        outcome,
        previousStatus: sample["previous_status"],
        reference: { ...reference, currencyCode: reference.currencyCode },
        resultingStatus:
          typeof sample["resulting_status"] === "string" ? sample["resulting_status"] : null,
      })
    }
  }
  const parsedCounts = {
    failed: counts["failed"],
    removed: counts["removed"],
    unverified: counts["unverified"],
  }
  if (
    !value["samples_truncated"] &&
    rows.length !== parsedCounts.removed + parsedCounts.failed + parsedCounts.unverified
  ) {
    return null
  }
  return { counts: parsedCounts, rows, samplesTruncated: value["samples_truncated"] }
}
