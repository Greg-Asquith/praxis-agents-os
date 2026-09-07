// apps/web/src/integrations/google_ads/presenters/dismiss-recommendations.tsx

import { countByKind, outcomeDetails, outcomeTone } from "@/integrations/google_ads/lib/outcomes"
import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Stat, StatGroup } from "@/components/ui/stat"
import { humanizeGoogleAdsToken } from "@/integrations/google_ads/lib/device-bid-modifiers"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"
import { parseRecommendationReference } from "@/integrations/google_ads/lib/recommendations"
import { isRecord, isNullableString } from "@/lib/guards"

type RecommendationReference = {
  label: string
  recommendationType: string
  resourceName: string
}

type DismissRecommendationArgs = {
  recommendations: RecommendationReference[]
}

type DismissRecommendationOutcome = {
  affectedCampaigns: string[]
  errorCode: string | null
  label: string
  message: string | null
  outcome: "dismissed" | "already_dismissed" | "failed" | "unverified"
  recommendationType: string
  resourceName: string
}

type DismissRecommendationResult = {
  recommendations: DismissRecommendationOutcome[]
}

const COLUMNS: DataColumn[] = [
  { key: "recommendation", kind: "text", label: "Recommendation" },
  { key: "type", kind: "text", label: "Google Type" },
  { key: "campaigns", kind: "text", label: "Affected Campaigns" },
  { key: "resourceName", kind: "id", label: "Resource Name" },
  { key: "outcome", kind: "status", label: "Outcome" },
  { key: "details", kind: "text", label: "Details" },
]

export const googleAdsDismissRecommendationsPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-dismiss-recommendations",
  variants: {
    google_ads_dismiss_recommendations: defineGoogleAdsWriteVariant({
      approval: {
        approveLabel: "Approve & Dismiss",
        label: "Dismiss Google Ads Recommendations",
        parseArgs: dismissRecommendationArgs,
        prompt:
          "Dismissal hides these Google proposals. It does not apply the recommended account changes.",
        renderSummary: (value, fallback) =>
          dismissRecommendationApprovalSummary(dismissRecommendationArgs(value) ?? fallback),
        title: "Dismiss Google Ads Recommendations",
        validateArgs: dismissRecommendationArgsError,
      },
      deniedDescription:
        "This dismissal was declined. The recommendations remain visible in Google Ads.",
      details: (args) =>
        args ? [{ label: "Recommendations", value: String(args.recommendations.length) }] : [],
      emptyLabel: "No Google Ads accounts dismissed recommendations.",
      failedDescription: "The dismissal did not finish. No recommendation was confirmed as hidden.",
      heading: "Dismiss Recommendations",
      malformedDescription:
        "The system couldn't verify this account's recommendation dismissal outcomes. Check Google Ads before taking further action.",
      parseResult: dismissRecommendationResult,
      progressLabel: "Dismissing Google Ads recommendations…",
      renderFailure: (args, description) => recommendationFailure(args, description),
      renderOutcome: dismissRecommendationOutcomeTable,
      resultAriaLabel: "Google Ads recommendation dismissal results",
      resultFailure:
        "The system couldn't verify the recommendation dismissals. Check Google Ads before taking further action.",
      unconfirmedAriaLabel: "Unconfirmed Google Ads recommendation dismissal",
      unverifiedDescription:
        "The system couldn't verify whether Google Ads dismissed these recommendations. Check Google Ads before taking further action.",
      waitingLabel: "Waiting for dismissal approval…",
    }),
  },
})

function dismissRecommendationApprovalSummary(args: DismissRecommendationArgs) {
  return (
    <section
      aria-label="Recommendations to dismiss"
      className="border-border bg-muted/35 grid gap-2 rounded-lg border px-3 py-2.5"
    >
      <p className="text-muted-foreground text-xs">
        {String(args.recommendations.length)} selected Google Ads
        {args.recommendations.length === 1 ? " recommendation" : " recommendations"}
      </p>
      <div className="grid gap-1.5 sm:grid-cols-2">
        {args.recommendations.map((recommendation) => (
          <div
            className="bg-card min-w-0 rounded-md border px-2.5 py-2"
            key={recommendation.resourceName}
          >
            <p className="truncate text-sm font-medium">{recommendation.label}</p>
            <p className="text-muted-foreground text-xs">
              {humanizeGoogleAdsToken(recommendation.recommendationType)}
            </p>
          </div>
        ))}
      </div>
    </section>
  )
}

function dismissRecommendationOutcomeTable(result: DismissRecommendationResult) {
  const counts = countByKind(result.recommendations)
  const rows: DataRow[] = result.recommendations.map((recommendation) => ({
    campaigns: recommendation.affectedCampaigns.join(", ") || "No campaign identified",
    details: outcomeDetails(recommendation.message, recommendation.errorCode, null) || "—",
    outcome:
      recommendation.outcome === "already_dismissed"
        ? "Already dismissed"
        : humanizeGoogleAdsToken(recommendation.outcome),
    recommendation: recommendation.label,
    resourceName: recommendation.resourceName,
    type: humanizeGoogleAdsToken(recommendation.recommendationType),
  }))
  return (
    <DataTable
      columns={COLUMNS}
      exportFilename="google-ads-dismissed-recommendations.csv"
      header={
        <StatGroup className="px-3 pt-2">
          {counts.map(({ kind, label, count }) => (
            <Stat
              key={kind}
              label={
                kind === "applied" ? "Dismissed" : kind === "skipped" ? "Already dismissed" : label
              }
              tone={count > 0 ? (kind === "skipped" ? "warning" : outcomeTone(kind)) : undefined}
              value={count}
            />
          ))}
        </StatGroup>
      }
      pageSize={25}
      rows={rows}
    />
  )
}

function recommendationFailure(args: DismissRecommendationArgs | null, description: string) {
  return (
    <div className="grid gap-2">
      <p className="text-destructive text-sm">{description}</p>
      {args ? (
        <div className="flex flex-wrap gap-1">
          {args.recommendations.map((recommendation) => (
            <span
              className="bg-muted rounded px-1.5 py-1 text-xs"
              key={recommendation.resourceName}
            >
              {recommendation.label}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function dismissRecommendationArgs(value: unknown): DismissRecommendationArgs | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["recommendations"]) ||
    value["recommendations"].length === 0 ||
    value["recommendations"].length > 100
  ) {
    return null
  }
  const recommendations: RecommendationReference[] = []
  for (const item of value["recommendations"]) {
    const reference = parseRecommendationReference(item)
    if (!reference) return null
    recommendations.push(reference)
  }
  return new Set(recommendations.map((item) => item.resourceName)).size === recommendations.length
    ? { recommendations }
    : null
}

function dismissRecommendationArgsError(value: unknown): string | null {
  return dismissRecommendationArgs(value)
    ? null
    : "Choose one or more valid recommendations without duplicates."
}

function dismissRecommendationResult(value: unknown): DismissRecommendationResult | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["recommendations"]) ||
    value["recommendations"].length === 0
  ) {
    return null
  }
  const recommendations = value["recommendations"].map(parseOutcome)
  const resourceNames = recommendations.map((item) => item?.resourceName)
  return recommendations.some((item) => item === null) ||
    new Set(resourceNames).size !== resourceNames.length
    ? null
    : {
        recommendations: recommendations.filter(
          (item): item is DismissRecommendationOutcome => item !== null
        ),
      }
}

function parseOutcome(value: unknown): DismissRecommendationOutcome | null {
  if (
    !isRecord(value) ||
    typeof value["recommendation_resource_name"] !== "string" ||
    typeof value["recommendation_type"] !== "string" ||
    typeof value["recommendation_label"] !== "string" ||
    !Array.isArray(value["affected_campaigns"]) ||
    !value["affected_campaigns"].every((item) => typeof item === "string") ||
    (value["outcome"] !== "dismissed" &&
      value["outcome"] !== "already_dismissed" &&
      value["outcome"] !== "failed" &&
      value["outcome"] !== "unverified")
  ) {
    return null
  }
  const message = value["message"] ?? null
  const errorCode = value["error_code"] ?? null
  if (!isNullableString(message) || !isNullableString(errorCode)) return null
  return {
    affectedCampaigns: value["affected_campaigns"],
    errorCode,
    label: value["recommendation_label"],
    message,
    outcome: value["outcome"],
    recommendationType: value["recommendation_type"],
    resourceName: value["recommendation_resource_name"],
  }
}
