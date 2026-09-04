// apps/web/src/integrations/google_ads/presenters/apply-recommendations.tsx

import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Stat, StatGroup } from "@/components/ui/stat"
import { humanizeGoogleAdsToken } from "@/integrations/google_ads/lib/device-bid-modifiers"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"
import { microsToCurrencyUnits } from "@/lib/format"
import { isRecord } from "@/lib/guards"

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
  { key: "outcome", kind: "status", label: "Outcome" },
  { key: "details", kind: "text", label: "Details" },
]

export const googleAdsApplyRecommendationsPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-apply-recommendations",
  variants: {
    google_ads_apply_recommendations: defineGoogleAdsWriteVariant({
      approval: {
        approveLabel: "Approve & Apply",
        label: "Apply Google Ads Recommendations",
        parseArgs: applyRecommendationArgs,
        prompt:
          "Review every recommendation and any custom parameters before applying Google's proposed account changes.",
        renderSummary: (value, fallback) =>
          applyRecommendationApprovalSummary(applyRecommendationArgs(value) ?? fallback),
        title: "Apply Google Ads Recommendations",
        validateArgs: applyRecommendationArgsError,
      },
      deniedDescription: "These recommendation changes were declined. Nothing was applied.",
      details: (args) =>
        args ? [{ label: "Recommendations", value: String(args.recommendations.length) }] : [],
      emptyLabel: "No Google Ads accounts applied recommendations.",
      failedDescription: "The apply action did not finish. No recommendation change was confirmed.",
      heading: "Apply Recommendations",
      malformedDescription:
        "The system couldn't verify this account's recommendation outcomes. Check Google Ads before taking further action.",
      parseResult: applyRecommendationResult,
      progressLabel: "Applying Google Ads recommendations…",
      renderFailure: (args, description) => recommendationFailure(args, description),
      renderOutcome: applyRecommendationOutcomeTable,
      resultAriaLabel: "Google Ads recommendation apply results",
      resultFailure:
        "The system couldn't verify the recommendation changes. Check Google Ads before taking further action.",
      unconfirmedAriaLabel: "Unconfirmed Google Ads recommendation apply",
      unverifiedDescription:
        "The system couldn't verify whether Google Ads applied these recommendations. Check Google Ads before taking further action.",
      waitingLabel: "Waiting for recommendation approval…",
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
    <section
      aria-label="Recommendations to apply"
      className="border-border bg-muted/35 grid gap-2 rounded-lg border px-3 py-2.5"
    >
      <p className="text-muted-foreground text-xs">
        {String(args.recommendations.length)} selected Google Ads
        {args.recommendations.length === 1 ? " recommendation" : " recommendations"}
      </p>
      <div className="grid gap-1.5">
        {args.recommendations.map((recommendation) => {
          const parameters = parametersByName.get(recommendation.resourceName)
          return (
            <div
              className="bg-card grid min-w-0 gap-1 rounded-md border px-2.5 py-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]"
              key={recommendation.resourceName}
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{recommendation.label}</p>
                <p className="text-muted-foreground text-xs">
                  {humanizeGoogleAdsToken(recommendation.recommendationType)}
                </p>
              </div>
              <p className="text-muted-foreground min-w-0 text-xs sm:text-right">
                {parameters ? formatParameters(parameters) : "Use Google's proposed values"}
              </p>
            </div>
          )
        })}
      </div>
    </section>
  )
}

function applyRecommendationOutcomeTable(result: ApplyRecommendationResult) {
  const counts = countOutcomes(result.recommendations)
  const rows: DataRow[] = result.recommendations.map((recommendation) => ({
    campaigns: recommendation.affectedCampaigns.join(", ") || "No campaign identified",
    details: outcomeDetails(recommendation),
    impact: formatImpact(recommendation.impact),
    outcome: humanizeGoogleAdsToken(recommendation.outcome),
    parameters: recommendation.parameters
      ? formatParameters(recommendation.parameters)
      : "Google's proposed values",
    recommendation: recommendation.label,
    resourceName: recommendation.resourceName,
    type: humanizeGoogleAdsToken(recommendation.recommendationType),
  }))
  return (
    <DataTable
      columns={COLUMNS}
      exportFilename="google-ads-applied-recommendations.csv"
      header={
        <div className="grid gap-2">
          <StatGroup className="px-3 pt-2">
            <Stat
              label="Applied"
              tone={counts.applied > 0 ? "success" : undefined}
              value={counts.applied}
            />
            <Stat
              label="Failed"
              tone={counts.failed > 0 ? "danger" : undefined}
              value={counts.failed}
            />
            <Stat
              label="Unverified"
              tone={counts.unverified > 0 ? "warning" : undefined}
              value={counts.unverified}
            />
          </StatGroup>
          <p className="text-muted-foreground px-3 text-xs">
            Forecast values are estimates from Google Ads.
          </p>
        </div>
      }
      pageSize={25}
      rows={rows}
    />
  )
}

function recommendationFailure(args: ApplyRecommendationArgs | null, description: string) {
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
    if (
      !isRecord(item) ||
      item["entity_kind"] !== "google_ads_recommendation" ||
      typeof item["customer_id"] !== "string" ||
      typeof item["resource_name"] !== "string" ||
      typeof item["recommendation_type"] !== "string" ||
      typeof item["label"] !== "string" ||
      !item["customer_id"].trim() ||
      !item["resource_name"].trim() ||
      !item["recommendation_type"].trim() ||
      !item["label"].trim()
    ) {
      return null
    }
    references.push({
      customerId: item["customer_id"],
      label: item["label"],
      recommendationType: item["recommendation_type"],
      resourceName: item["resource_name"],
    })
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
        new_budget_amount_micros: positiveInteger,
      })
    case "keyword":
      return validParameter(value, common, ["ad_group", "match_type"], {
        ad_group: nonEmptyString,
        cpc_bid_micros: optionalPositiveInteger,
        match_type: (item) => item === "EXACT" || item === "PHRASE" || item === "BROAD",
      })
    case "targetCpaOptIn":
      return validParameter(value, common, ["target_cpa_micros"], {
        new_campaign_budget_amount_micros: optionalPositiveInteger,
        target_cpa_micros: positiveInteger,
      })
    case "targetRoasOptIn":
      return validOptionalPair(
        value,
        common,
        "target_roas",
        roas,
        "new_campaign_budget_amount_micros",
        positiveInteger
      )
    case "moveUnusedBudget":
      return validParameter(value, common, ["budget_micros_to_move"], {
        budget_micros_to_move: positiveInteger,
      })
    case "useBroadMatchKeyword":
      return validParameter(value, common, ["new_budget_amount_micros"], {
        new_budget_amount_micros: positiveInteger,
      })
    case "raiseTargetCpaBidTooLow":
      return validParameter(value, common, ["target_multiplier"], {
        target_multiplier: (item) => finiteNumber(item) && item > 1,
      })
    case "forecastingSetTargetRoas":
    case "setTargetRoas":
      return validOptionalPair(
        value,
        common,
        "target_roas",
        roas,
        "campaign_budget_amount_micros",
        positiveInteger
      )
    case "raiseTargetCpa":
      return validParameter(value, common, ["target_cpa_multiplier"], {
        target_cpa_multiplier: positiveNumber,
      })
    case "lowerTargetRoas":
      return validParameter(value, common, ["target_roas_multiplier"], {
        target_roas_multiplier: positiveNumber,
      })
    case "forecastingSetTargetCpa":
    case "setTargetCpa":
      return validOptionalPair(
        value,
        common,
        "target_cpa_micros",
        positiveInteger,
        "campaign_budget_amount_micros",
        positiveInteger
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
  if (value[firstKey] === null && value[secondKey] === null) return null
  if (value[firstKey] === undefined && value[secondKey] === undefined) return null
  return validParameter(value, commonKeys, [], {
    [firstKey]: firstValidator,
    [secondKey]: secondValidator,
  })
}

function nonEmptyString(value: unknown): boolean {
  return typeof value === "string" && value.trim().length > 0
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value)
}

function positiveNumber(value: unknown): boolean {
  return finiteNumber(value) && value > 0
}

function positiveInteger(value: unknown): boolean {
  return positiveNumber(value) && Number.isInteger(value)
}

function optionalPositiveInteger(value: unknown): boolean {
  return value === null || positiveInteger(value)
}

function roas(value: unknown): boolean {
  return finiteNumber(value) && value >= 0.01 && value <= 1_000
}

function applyRecommendationResult(value: unknown): ApplyRecommendationResult | null {
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
          (item): item is ApplyRecommendationOutcome => item !== null
        ),
      }
}

function parseOutcome(value: unknown): ApplyRecommendationOutcome | null {
  if (
    !isRecord(value) ||
    typeof value["recommendation_resource_name"] !== "string" ||
    typeof value["recommendation_type"] !== "string" ||
    typeof value["recommendation_label"] !== "string" ||
    !Array.isArray(value["affected_campaigns"]) ||
    !value["affected_campaigns"].every((item) => typeof item === "string") ||
    (value["outcome"] !== "applied" &&
      value["outcome"] !== "failed" &&
      value["outcome"] !== "unverified")
  ) {
    return null
  }
  const parameters =
    value["requested_parameters"] === null ? null : parseParameters(value["requested_parameters"])
  const impact = value["impact"] === null ? null : parseImpact(value["impact"])
  const message = optionalString(value["message"])
  const errorCode = optionalString(value["error_code"])
  if (parameters === null && value["requested_parameters"] !== null) return null
  if (impact === null && value["impact"] !== null) return null
  if (message === undefined || errorCode === undefined) return null
  return {
    affectedCampaigns: value["affected_campaigns"],
    errorCode,
    impact,
    label: value["recommendation_label"],
    message,
    outcome: value["outcome"],
    parameters,
    recommendationType: value["recommendation_type"],
    resourceName: value["recommendation_resource_name"],
  }
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
  const parsed = Object.fromEntries(keys.map((key) => [key, optionalNumber(value[key])]))
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
    const label = parameterLabel(key)
    const rendered = key.endsWith("_micros")
      ? `${formatNumber(microsToCurrencyUnits(Number(value)))} account currency units`
      : key.includes("roas") || key.includes("multiplier")
        ? `${formatNumber(Number(value))}×`
        : humanizeGoogleAdsToken(String(value))
    parts.push(`${label}: ${rendered}`)
  }
  return parts.join(" · ") || humanizeGoogleAdsToken(String(parameters["parameter_type"]))
}

function parameterLabel(key: string): string {
  return humanizeGoogleAdsToken(key.replace(/_micros$/, ""))
    .replaceAll("Cpa", "CPA")
    .replaceAll("Cpc", "CPC")
    .replaceAll("Roas", "ROAS")
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
            `${formatNumber(microsToCurrencyUnits(number))} account currency units`
        : formatNumber
    return [`${label}: ${render(base)} → ${render(potential)}`]
  })
  return parts.join(" · ") || "No estimate provided"
}

function countOutcomes(recommendations: ApplyRecommendationOutcome[]) {
  return {
    applied: recommendations.filter((item) => item.outcome === "applied").length,
    failed: recommendations.filter((item) => item.outcome === "failed").length,
    unverified: recommendations.filter((item) => item.outcome === "unverified").length,
  }
}

function outcomeDetails(outcome: ApplyRecommendationOutcome): string {
  return (
    [outcome.message, outcome.errorCode ? humanizeGoogleAdsToken(outcome.errorCode) : null]
      .filter((item): item is string => Boolean(item))
      .join(" · ") || "—"
  )
}

function optionalString(value: unknown): string | null | undefined {
  return value === null || value === undefined
    ? null
    : typeof value === "string"
      ? value
      : undefined
}

function optionalNumber(value: unknown): number | null | undefined {
  return value === null || value === undefined
    ? null
    : typeof value === "number" && Number.isFinite(value)
      ? value
      : undefined
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value)
}
