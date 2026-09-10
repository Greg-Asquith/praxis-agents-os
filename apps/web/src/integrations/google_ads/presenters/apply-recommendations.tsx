// apps/web/src/integrations/google_ads/presenters/apply-recommendations.tsx

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
import { countByKind } from "@/integrations/google_ads/lib/outcomes"
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
import { microsToCurrencyUnits } from "@/lib/format"
import { isNullableFiniteNumber, isPositiveInteger, isRecord } from "@/lib/guards"

const NUMBER_FORMAT = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 })

const PARAMETER_TYPES = new Set([
  "campaignBudget",
  "keyword",
  "targetCpaOptIn",
  "targetRoasOptIn",
  "moveUnusedBudget",
  "useBroadMatchKeyword",
  "raiseTargetCpaBidTooLow",
  "forecastingSetTargetRoas",
  "raiseTargetCpa",
  "lowerTargetRoas",
  "forecastingSetTargetCpa",
  "setTargetCpa",
  "setTargetRoas",
])

type RecommendationReference = {
  customerId: string
  label: string
  recommendationType: string
  resourceName: string
}

type RecommendationParameters = Record<string, string | number | null>

type ApplyRecommendationArgs = {
  parameters: RecommendationParameters[]
  recommendations: RecommendationReference[]
}

type Metrics = {
  clicks: number | null
  conversions: number | null
  conversionsValue: number | null
  costMicros: number | null
  impressions: number | null
  videoViews: number | null
}

type Impact = {
  base: Metrics | null
  potential: Metrics | null
}

type ApplyRecommendationOutcome = {
  affectedCampaigns: string[]
  errorCode: string | null
  impact: Impact | null
  label: string
  message: string | null
  outcome: "applied" | "failed" | "unverified"
  parameters: RecommendationParameters | null
  recommendationType: string
  resourceName: string
}

type ApplyRecommendationResult = {
  recommendations: ApplyRecommendationOutcome[]
}

const COLUMNS: DataColumn[] = [
  { key: "recommendation", kind: "text", label: "Recommendation" },
  { key: "type", kind: "text", label: "Google Type" },
  { key: "campaigns", kind: "text", label: "Affected Campaigns" },
  { key: "resourceName", kind: "id", label: "Resource Name" },
  { key: "parameters", kind: "text", label: "Requested Parameters" },
  { key: "impact", kind: "text", label: "Google Estimate" },
]

export const googleAdsApplyRecommendationsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_apply_recommendations: defineIntegrationWriteVariant(googleAdsProvider, {
      copy: { verb: "Apply", object: "recommendations", effect: "applied" },
      approval: {
        parseArgs: applyRecommendationArgs,
        prompt:
          "Review every recommendation and any custom parameters before applying Google's proposed account changes.",
        renderSummary: (value, fallback) =>
          applyRecommendationApprovalSummary(applyRecommendationArgs(value) ?? fallback),
        validateArgs: applyRecommendationArgsError,
      },
      details: (args) =>
        args ? [{ label: "Recommendations", value: String(args.recommendations.length) }] : [],
      parseResult: applyRecommendationResult,
      renderFailure: (args, description) => (
        <GoogleAdsFailureTargets
          description={description}
          targets={args?.recommendations.map((item) => item.label) ?? []}
        />
      ),
      renderOutcome: applyRecommendationOutcomeTable,
    }),
  },
})

function applyRecommendationApprovalSummary(args: ApplyRecommendationArgs) {
  const parametersByName = new Map(
    args.parameters.map((parameter) => [
      String(parameter["recommendation_resource_name"]),
      parameter,
    ])
  )
  return (
    <GoogleAdsApprovalSection
      ariaLabel="Recommendations to apply"
      countLine={approvalCountLine(args.recommendations.length, "recommendation")}
    >
      {args.recommendations.map((recommendation) => {
        const parameters = parametersByName.get(recommendation.resourceName)
        return (
          <GoogleAdsEntityCard
            key={recommendation.resourceName}
            title={recommendation.label}
            meta={googleAdsTokenLabel(recommendation.recommendationType)}
            trailing={
              <span className="text-muted-foreground text-xs">
                {parameters ? formatParameters(parameters) : "Use Google's proposed values"}
              </span>
            }
          />
        )
      })}
    </GoogleAdsApprovalSection>
  )
}

function applyRecommendationOutcomeTable(result: ApplyRecommendationResult) {
  const counts = countByKind(result.recommendations)
  const rows: GoogleAdsOutcomeRow[] = result.recommendations.map((recommendation) => ({
    campaigns: recommendation.affectedCampaigns.join(", ") || "No campaign identified",
    details: recommendation.message ?? "",
    errorCode: recommendation.errorCode,
    impact: formatImpact(recommendation.impact),
    outcome: recommendation.outcome,
    parameters: recommendation.parameters
      ? formatParameters(recommendation.parameters)
      : "Google's proposed values",
    recommendation: recommendation.label,
    resourceName: recommendation.resourceName,
    type: googleAdsTokenLabel(recommendation.recommendationType),
  }))
  return (
    <div className="grid gap-2">
      <GoogleAdsOutcomeTable
        columns={COLUMNS}
        rows={rows}
        outcomes={counts.filter(({ kind }) => kind !== "skipped")}
        exportFilename="google-ads-applied-recommendations.csv"
      />
      <p className="text-muted-foreground px-3 text-xs">
        Forecast values are estimates from Google Ads.
      </p>
    </div>
  )
}

function applyRecommendationArgs(value: unknown): ApplyRecommendationArgs | null {
  if (!isRecord(value) || !Array.isArray(value["recommendations"])) {
    return null
  }
  const recommendations = parseReferences(value["recommendations"])
  const parametersValue = value["parameters"]
  const parameters =
    parametersValue === undefined || parametersValue === null
      ? []
      : Array.isArray(parametersValue)
        ? parametersValue.map(parseParameters)
        : [null]
  if (
    !recommendations ||
    recommendations.length > 50 ||
    parameters.length > 50 ||
    parameters.some((parameter) => parameter === null)
  ) {
    return null
  }
  const parsedParameters = parameters.filter(
    (parameter): parameter is RecommendationParameters => parameter !== null
  )
  const selected = new Set(recommendations.map((item) => item.resourceName))
  const parameterNames = parsedParameters.map((item) =>
    String(item["recommendation_resource_name"])
  )
  if (
    new Set(recommendations.map((item) => item.resourceName)).size !== recommendations.length ||
    new Set(parameterNames).size !== parameterNames.length ||
    parameterNames.some((name) => !selected.has(name))
  ) {
    return null
  }
  return { parameters: parsedParameters, recommendations }
}

function applyRecommendationArgsError(value: unknown): string | null {
  return applyRecommendationArgs(value)
    ? null
    : "Choose valid recommendations and match each custom parameter row to one selected recommendation."
}

function parseReferences(value: unknown[]): RecommendationReference[] | null {
  if (value.length === 0) {
    return null
  }
  const references: RecommendationReference[] = []
  for (const item of value) {
    const reference = parseRecommendationReference(item)
    if (!reference) return null
    references.push(reference)
  }
  return references
}

function parseParameters(value: unknown): RecommendationParameters | null {
  if (
    !isRecord(value) ||
    typeof value["recommendation_resource_name"] !== "string" ||
    typeof value["parameter_type"] !== "string" ||
    !PARAMETER_TYPES.has(value["parameter_type"])
  ) {
    return null
  }
  const common = ["parameter_type", "recommendation_resource_name"]
  switch (value["parameter_type"]) {
    case "campaignBudget":
      return validParameter(value, common, ["new_budget_amount_micros"], {
        new_budget_amount_micros: isPositiveInteger,
      })
    case "keyword":
      return validParameter(value, common, ["ad_group", "match_type"], {
        ad_group: (item) => typeof item === "string" && item.trim().length > 0,
        cpc_bid_micros: isPositiveInteger,
        match_type: (item) => item === "EXACT" || item === "PHRASE" || item === "BROAD",
      })
    case "targetCpaOptIn":
      return validParameter(value, common, ["target_cpa_micros"], {
        new_campaign_budget_amount_micros: isPositiveInteger,
        target_cpa_micros: isPositiveInteger,
      })
    case "targetRoasOptIn":
      return validOptionalPair(
        value,
        common,
        "target_roas",
        (item) => typeof item === "number" && item >= 0.01 && item <= 1_000,
        "new_campaign_budget_amount_micros",
        isPositiveInteger
      )
    case "moveUnusedBudget":
      return validParameter(value, common, ["budget_micros_to_move"], {
        budget_micros_to_move: isPositiveInteger,
      })
    case "useBroadMatchKeyword":
      return validParameter(value, common, ["new_budget_amount_micros"], {
        new_budget_amount_micros: isPositiveInteger,
      })
    case "raiseTargetCpaBidTooLow":
      return validParameter(value, common, ["target_multiplier"], {
        target_multiplier: (item) => typeof item === "number" && Number.isFinite(item) && item > 1,
      })
    case "forecastingSetTargetRoas":
    case "setTargetRoas":
      return validOptionalPair(
        value,
        common,
        "target_roas",
        (item) => typeof item === "number" && item >= 0.01 && item <= 1_000,
        "campaign_budget_amount_micros",
        isPositiveInteger
      )
    case "raiseTargetCpa":
      return validParameter(value, common, ["target_cpa_multiplier"], {
        target_cpa_multiplier: (item) =>
          typeof item === "number" && Number.isFinite(item) && item > 0,
      })
    case "lowerTargetRoas":
      return validParameter(value, common, ["target_roas_multiplier"], {
        target_roas_multiplier: (item) =>
          typeof item === "number" && Number.isFinite(item) && item > 0,
      })
    case "forecastingSetTargetCpa":
    case "setTargetCpa":
      return validOptionalPair(
        value,
        common,
        "target_cpa_micros",
        isPositiveInteger,
        "campaign_budget_amount_micros",
        isPositiveInteger
      )
  }
  return null
}

type ScalarValidator = (value: unknown) => boolean

function validParameter(
  value: Record<string, unknown>,
  commonKeys: string[],
  requiredKeys: string[],
  validators: Record<string, ScalarValidator>
): RecommendationParameters | null {
  const allowedKeys = new Set([...commonKeys, ...Object.keys(validators)])
  if (
    Object.keys(value).some((key) => !allowedKeys.has(key)) ||
    requiredKeys.some(
      (key) => !(key in value) || value[key] === null || !validators[key]?.(value[key])
    ) ||
    Object.entries(validators).some(
      ([key, validator]) => key in value && value[key] !== null && !validator(value[key])
    )
  ) {
    return null
  }
  return value as RecommendationParameters
}

function validOptionalPair(
  value: Record<string, unknown>,
  commonKeys: string[],
  firstKey: string,
  firstValidator: ScalarValidator,
  secondKey: string,
  secondValidator: ScalarValidator
): RecommendationParameters | null {
  if ((value[firstKey] ?? null) === null && (value[secondKey] ?? null) === null) return null
  return validParameter(value, commonKeys, [], {
    [firstKey]: firstValidator,
    [secondKey]: secondValidator,
  })
}

function applyRecommendationResult(value: unknown): ApplyRecommendationResult | null {
  const recommendations = parseOutcomeList(
    value,
    "recommendations",
    parseApplyOutcome,
    (row) => row.resourceName
  )
  return recommendations?.length ? { recommendations } : null
}

function parseApplyOutcome(value: unknown): ApplyRecommendationOutcome | null {
  const common = parseRecommendationOutcome(value, ["applied", "failed", "unverified"] as const)
  if (!common || !isRecord(value)) return null
  const parameters =
    value["requested_parameters"] === null ? null : parseParameters(value["requested_parameters"])
  const impact = value["impact"] === null ? null : parseImpact(value["impact"])
  if (parameters === null && value["requested_parameters"] !== null) return null
  if (impact === null && value["impact"] !== null) return null
  return { ...common, parameters, impact }
}

function parseImpact(value: unknown): Impact | null {
  if (!isRecord(value)) return null
  const base = value["base_metrics"] === null ? null : parseMetrics(value["base_metrics"])
  const potential =
    value["potential_metrics"] === null ? null : parseMetrics(value["potential_metrics"])
  return base === null && value["base_metrics"] !== null
    ? null
    : potential === null && value["potential_metrics"] !== null
      ? null
      : { base, potential }
}

function parseMetrics(value: unknown): Metrics | null {
  if (!isRecord(value)) return null
  const keys = [
    "impressions",
    "clicks",
    "cost_micros",
    "conversions",
    "conversions_value",
    "video_views",
  ] as const
  const parsed = Object.fromEntries(
    keys.map((key) => {
      const metric = value[key] ?? null
      return [key, isNullableFiniteNumber(metric) ? metric : undefined]
    })
  )
  if (Object.values(parsed).some((item) => item === undefined)) return null
  return {
    clicks: parsed["clicks"] ?? null,
    conversions: parsed["conversions"] ?? null,
    conversionsValue: parsed["conversions_value"] ?? null,
    costMicros: parsed["cost_micros"] ?? null,
    impressions: parsed["impressions"] ?? null,
    videoViews: parsed["video_views"] ?? null,
  }
}

function formatParameters(parameters: RecommendationParameters): string {
  const parts: string[] = []
  for (const [key, value] of Object.entries(parameters)) {
    if (key === "recommendation_resource_name" || key === "parameter_type" || value === null)
      continue
    const label = googleAdsTokenLabel(key.replace(/_micros$/, ""))
    const rendered = key.endsWith("_micros")
      ? `${NUMBER_FORMAT.format(microsToCurrencyUnits(Number(value)))} account currency units`
      : key.includes("roas") || key.includes("multiplier")
        ? `${NUMBER_FORMAT.format(Number(value))}×`
        : googleAdsTokenLabel(String(value))
    parts.push(`${label}: ${rendered}`)
  }
  return parts.join(" · ") || googleAdsTokenLabel(String(parameters["parameter_type"]))
}

function formatImpact(impact: Impact | null): string {
  if (!impact) return "No estimate provided"
  const labels: [keyof Metrics, string][] = [
    ["clicks", "Clicks"],
    ["conversions", "Conversions"],
    ["impressions", "Impressions"],
    ["videoViews", "Video views"],
    ["conversionsValue", "Conversion value"],
    ["costMicros", "Cost"],
  ]
  const parts = labels.flatMap(([key, label]) => {
    const base = impact.base?.[key]
    const potential = impact.potential?.[key]
    if (base === null || base === undefined || potential === null || potential === undefined)
      return []
    const render =
      key === "costMicros"
        ? (number: number) =>
            `${NUMBER_FORMAT.format(microsToCurrencyUnits(number))} account currency units`
        : (number: number) => NUMBER_FORMAT.format(number)
    return [`${label}: ${render(base)} → ${render(potential)}`]
  })
  return parts.join(" · ") || "No estimate provided"
}
