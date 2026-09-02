// apps/web/src/integrations/google_ads/presenters/assign-campaign-budgets.tsx

import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Stat, StatGroup } from "@/components/ui/stat"
import {
  budgetPeriodLabel,
  linkedCampaignLabel,
  parseCampaignBudgetReference,
  parseCampaignReference,
  type CampaignBudgetReference,
  type CampaignReference,
} from "@/integrations/google_ads/lib/campaign-budgets"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"
import { titleCaseToken } from "@/lib/format"
import { isNonNegativeInteger, isNullableString, isRecord } from "@/lib/guards"

const OUTCOMES = ["assigned", "already_set", "failed", "unverified"] as const
type AssignmentOutcome = (typeof OUTCOMES)[number]

type AssignmentArgs = {
  campaigns: CampaignReference[]
  destination: CampaignBudgetReference
  routes: AssignmentRoute[]
}

type AssignmentRoute = {
  campaign: CampaignReference
  destinationBudget: CampaignBudgetReference
  previousBudget: CampaignBudgetReference
}

type AssignmentResultRow = {
  campaign: CampaignReference
  errorCode: string | null
  message: string | null
  outcome: AssignmentOutcome
  previousBudget: CampaignBudgetReference
  requestedBudget: CampaignBudgetReference
}

type AssignmentResult = {
  counts: Record<AssignmentOutcome, number>
  destination: CampaignBudgetReference
  rows: AssignmentResultRow[]
  samplesTruncated: boolean
}

const COLUMNS: DataColumn[] = [
  { key: "campaign", kind: "text", label: "Campaign" },
  { key: "campaignId", kind: "id", label: "Campaign ID" },
  { key: "previousBudget", kind: "text", label: "From" },
  { key: "requestedBudget", kind: "text", label: "To" },
  { key: "route", kind: "text", label: "Budget Route", width: 260 },
  { key: "outcome", kind: "status", label: "Outcome" },
  { key: "details", kind: "text", label: "Details" },
]

export const googleAdsAssignCampaignBudgetsPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-assign-campaign-budgets",
  variants: {
    google_ads_assign_campaign_budgets: defineGoogleAdsWriteVariant({
      approval: {
        approveLabel: "Approve & Assign",
        label: "Assign Google Ads Campaign Budgets",
        parseArgs: assignmentArgs,
        prompt: "Review every campaign route before replacing its live campaign budget.",
        renderSummary: (value, fallback) =>
          renderAssignmentApprovalSummary(assignmentArgs(value) ?? fallback),
        title: "Assign Campaign Budgets",
      },
      deniedDescription: "This campaign budget assignment was declined. Nothing was changed.",
      details: (args) =>
        args
          ? [
              { label: "Destination", value: args.destination.label },
              { label: "Campaigns", value: String(args.campaigns.length) },
            ]
          : [],
      emptyLabel: "No Google Ads accounts assigned campaign budgets.",
      failedDescription: "The assignment did not finish. No campaign budget route was confirmed.",
      heading: "Assign Campaign Budgets",
      malformedDescription:
        "The system couldn't verify this account's campaign budget assignment outcomes. Check Google Ads before taking further action.",
      parseResult: assignmentResult,
      progressLabel: "Assigning Google Ads campaign budgets…",
      renderOutcome: renderAssignmentOutcomeTable,
      resultAriaLabel: "Google Ads campaign budget assignment results",
      resultFailure:
        "The system couldn't verify the campaign budget assignments. Check Google Ads before taking further action.",
      unconfirmedAriaLabel: "Unconfirmed Google Ads campaign budget assignment",
      unverifiedDescription:
        "The system couldn't verify whether Google Ads applied these campaign budget assignments. Check Google Ads before retrying.",
      waitingLabel: "Waiting for campaign budget assignment approval…",
    }),
  },
})

function renderAssignmentApprovalSummary(args: AssignmentArgs) {
  return (
    <section
      aria-label="Proposed campaign budget routes"
      className="border-border bg-muted/35 grid gap-2 rounded-lg border px-3 py-2.5"
    >
      <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-2">
        <p className="text-muted-foreground text-xs">Destination budget</p>
        <p className="truncate text-sm font-semibold">{args.destination.label}</p>
      </div>
      <div className="grid gap-1" role="list">
        {args.routes.map((route) => (
          <div
            className="bg-card grid min-w-0 gap-1 rounded-md border px-2.5 py-2 text-sm"
            key={route.campaign.campaignId}
            role="listitem"
          >
            <span className="truncate font-medium">{route.campaign.label}</span>
            <span className="flex min-w-0 items-center gap-2">
              <span className="min-w-0 flex-1 truncate">{route.previousBudget.label}</span>
              <span aria-hidden="true" className="text-muted-foreground">
                →
              </span>
              <span className="min-w-0 flex-1 truncate font-medium">
                {route.destinationBudget.label}
              </span>
            </span>
          </div>
        ))}
      </div>
      <p className="text-muted-foreground text-xs">
        {budgetPeriodLabel(args.destination.period)} ·{" "}
        {linkedCampaignLabel(args.destination.referenceCount)} use this budget before the change
      </p>
    </section>
  )
}

function renderAssignmentOutcomeTable(result: AssignmentResult) {
  const rows = result.rows.map<DataRow>((row) => {
    const details = [row.message]
    if (row.errorCode) {
      details.push(titleCaseToken(row.errorCode, row.errorCode))
    }
    return {
      campaign: row.campaign.label,
      campaignId: row.campaign.campaignId,
      details: details.filter((value): value is string => Boolean(value)).join(" · ") || "—",
      outcome:
        row.outcome === "already_set" ? "Already set" : titleCaseToken(row.outcome, row.outcome),
      previousBudget: row.previousBudget.label,
      requestedBudget: row.requestedBudget.label,
      route: `${row.previousBudget.label} → ${row.requestedBudget.label}`,
    }
  })
  return (
    <div className="grid gap-3">
      <section className="border-border bg-muted/35 rounded-lg border px-3 py-2.5">
        <p className="text-muted-foreground text-xs">Destination budget</p>
        <div className="mt-0.5 flex min-w-0 flex-wrap items-baseline justify-between gap-2">
          <p className="truncate text-sm font-medium">{result.destination.label}</p>
          <p className="text-muted-foreground text-xs">
            {budgetPeriodLabel(result.destination.period)} ·{" "}
            {linkedCampaignLabel(result.destination.referenceCount)}
          </p>
        </div>
      </section>
      <DataTable
        columns={COLUMNS}
        exportFilename="campaign-budget-assignments.csv"
        header={
          <StatGroup className="px-3 pt-2">
            <Stat
              label="Assigned"
              tone={result.counts.assigned > 0 ? "success" : undefined}
              value={result.counts.assigned}
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
        truncationNote={
          result.samplesTruncated
            ? "The table contains a representative sample. Complete evidence is available in the Audit Log."
            : null
        }
      />
    </div>
  )
}

function assignmentArgs(value: unknown): AssignmentArgs | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["campaigns"]) ||
    value["campaigns"].length === 0 ||
    !Array.isArray(value["_budget_routes"])
  ) {
    return null
  }
  const destination = parseCampaignBudgetReference(value["destination_budget"])
  if (!destination) {
    return null
  }
  const campaigns: CampaignReference[] = []
  const campaignIds = new Set<string>()
  for (const valueCampaign of value["campaigns"]) {
    const campaign = parseCampaignReference(valueCampaign)
    if (!campaign || campaignIds.has(campaign.campaignId)) {
      return null
    }
    campaignIds.add(campaign.campaignId)
    campaigns.push(campaign)
  }
  const routes: AssignmentRoute[] = []
  for (const routeValue of value["_budget_routes"]) {
    if (!isRecord(routeValue)) {
      return null
    }
    const campaign = parseCampaignReference(routeValue["campaign"])
    const previousBudget = parseCampaignBudgetReference(routeValue["previous_budget"])
    const destinationBudget = parseCampaignBudgetReference(routeValue["destination_budget"])
    if (!campaign || !previousBudget || !destinationBudget) {
      return null
    }
    routes.push({ campaign, destinationBudget, previousBudget })
  }
  if (
    routes.length !== campaigns.length ||
    routes.some(
      (route, index) =>
        route.campaign.campaignId !== campaigns[index]?.campaignId ||
        route.destinationBudget.customerId !== destination.customerId ||
        route.destinationBudget.budgetId !== destination.budgetId
    )
  ) {
    return null
  }
  return { campaigns, destination, routes }
}

function assignmentResult(value: unknown): AssignmentResult | null {
  if (
    !isRecord(value) ||
    !isRecord(value["counts"]) ||
    !isRecord(value["samples"]) ||
    typeof value["samples_truncated"] !== "boolean"
  ) {
    return null
  }
  const destination = parseCampaignBudgetReference(value["destination_budget"])
  const counts = value["counts"]
  if (
    !destination ||
    !isNonNegativeInteger(counts["assigned"]) ||
    !isNonNegativeInteger(counts["already_set"]) ||
    !isNonNegativeInteger(counts["failed"]) ||
    !isNonNegativeInteger(counts["unverified"])
  ) {
    return null
  }
  const rows: AssignmentResultRow[] = []
  for (const outcome of OUTCOMES) {
    const samples = value["samples"][outcome]
    if (!Array.isArray(samples)) {
      return null
    }
    for (const sample of samples) {
      if (!isRecord(sample) || sample["outcome"] !== outcome) {
        return null
      }
      const campaign = parseCampaignReference(sample["campaign"])
      const previousBudget = parseCampaignBudgetReference(sample["previous_budget"])
      const requestedBudget = parseCampaignBudgetReference(sample["requested_budget"])
      if (
        !campaign ||
        !previousBudget ||
        !requestedBudget ||
        !isNullableString(sample["error_code"] ?? null) ||
        !isNullableString(sample["message"] ?? null)
      ) {
        return null
      }
      rows.push({
        campaign,
        errorCode: typeof sample["error_code"] === "string" ? sample["error_code"] : null,
        message: typeof sample["message"] === "string" ? sample["message"] : null,
        outcome,
        previousBudget,
        requestedBudget,
      })
    }
  }
  const parsedCounts = {
    already_set: counts["already_set"],
    assigned: counts["assigned"],
    failed: counts["failed"],
    unverified: counts["unverified"],
  }
  if (
    !value["samples_truncated"] &&
    rows.length !==
      parsedCounts.assigned +
        parsedCounts.already_set +
        parsedCounts.failed +
        parsedCounts.unverified
  ) {
    return null
  }
  return { counts: parsedCounts, destination, rows, samplesTruncated: value["samples_truncated"] }
}
