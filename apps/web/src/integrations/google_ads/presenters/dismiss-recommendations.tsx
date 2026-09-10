// apps/web/src/integrations/google_ads/presenters/dismiss-recommendations.tsx

import { GoogleAdsApprovalSection } from "@/integrations/google_ads/components/approval-section"
import { GoogleAdsEntityCard } from "@/integrations/google_ads/components/entity-card"
import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import type { GoogleAdsOutcomeColumn as DataColumn } from "@/integrations/google_ads/components/outcome-table"
import {
  GoogleAdsOutcomeTable,
  type GoogleAdsOutcomeRow,
} from "@/integrations/google_ads/components/outcome-table"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { parseOutcomeList } from "@/integrations/google_ads/lib/envelopes"
import { countByKind, outcomeLabel } from "@/integrations/google_ads/lib/outcomes"
import {
  parseRecommendationOutcome,
  parseRecommendationReference,
} from "@/integrations/google_ads/lib/recommendations"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"
import { isRecord } from "@/lib/guards"

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
]

export const googleAdsDismissRecommendationsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_dismiss_recommendations: defineIntegrationWriteVariant(googleAdsProvider, {
      copy: { verb: "Dismiss", object: "recommendations", effect: "dismissed" },
      approval: {
        parseArgs: dismissRecommendationArgs,
        prompt:
          "Dismissal hides these Google proposals. It does not apply the recommended account changes.",
        renderSummary: (value, fallback) =>
          dismissRecommendationApprovalSummary(dismissRecommendationArgs(value) ?? fallback),
        validateArgs: dismissRecommendationArgsError,
      },
      deniedDescription:
        "This dismissal was declined. The recommendations remain visible in Google Ads.",
      details: (args) =>
        args ? [{ label: "Recommendations", value: String(args.recommendations.length) }] : [],
      parseResult: dismissRecommendationResult,
      renderFailure: (args, description) => (
        <GoogleAdsFailureTargets
          description={description}
          targets={args?.recommendations.map((item) => item.label) ?? []}
        />
      ),
      renderOutcome: dismissRecommendationOutcomeTable,
    }),
  },
})

function dismissRecommendationApprovalSummary(args: DismissRecommendationArgs) {
  return (
    <GoogleAdsApprovalSection
      ariaLabel="Recommendations to dismiss"
      countLine={approvalCountLine(args.recommendations.length, "recommendation")}
    >
      {args.recommendations.map((recommendation) => (
        <GoogleAdsEntityCard
          key={recommendation.resourceName}
          title={recommendation.label}
          meta={googleAdsTokenLabel(recommendation.recommendationType)}
        />
      ))}
    </GoogleAdsApprovalSection>
  )
}

function dismissRecommendationOutcomeTable(result: DismissRecommendationResult) {
  const counts = countByKind(result.recommendations)
  const rows: GoogleAdsOutcomeRow[] = result.recommendations.map((recommendation) => ({
    campaigns: recommendation.affectedCampaigns.join(", ") || "No campaign identified",
    details: recommendation.message ?? "",
    errorCode: recommendation.errorCode,
    outcome: recommendation.outcome,
    recommendation: recommendation.label,
    resourceName: recommendation.resourceName,
    type: googleAdsTokenLabel(recommendation.recommendationType),
  }))
  return (
    <GoogleAdsOutcomeTable
      columns={COLUMNS}
      rows={rows}
      outcomes={counts.map((item) => ({
        ...item,
        label:
          item.kind === "applied"
            ? outcomeLabel("dismissed")
            : item.kind === "skipped"
              ? outcomeLabel("already_dismissed")
              : item.label,
      }))}
      exportFilename="google-ads-dismissed-recommendations.csv"
    />
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
  const recommendations = parseOutcomeList(
    value,
    "recommendations",
    (value) =>
      parseRecommendationOutcome(value, [
        "dismissed",
        "already_dismissed",
        "failed",
        "unverified",
      ] as const),
    (row) => row.resourceName
  )
  return recommendations?.length ? { recommendations } : null
}
