// apps/web/src/integrations/google_ads/lib/campaign-build-result.ts

import { isNonEmptyString, isRecord } from "@/lib/guards"

type BuildKind =
  | "budget"
  | "campaign"
  | "location"
  | "excluded_location"
  | "ad_group"
  | "keyword"
  | "negative_keyword"
  | "ad"
  | "asset"
  | "asset_link"
  | "language"
  | "conversion_goal"
  | "text_asset"
  | "brand_link"
  | "asset_group"
  | "listing_filter"
  | "asset_group_link"
  | "search_theme"

export type BuildKindCount = {
  created: number
  failed: number
  kind: BuildKind
  unverified: number
}

type BuildProblem = { item: string; kind: BuildKind; message: string }

export type CampaignBuildResult = {
  campaignName: string
  kinds: BuildKindCount[]
  problems: BuildProblem[]
  requestedStatus: "PAUSED" | "ENABLED"
}

export const BUILD_KIND_LABELS: Record<BuildKind, { one: string; many: string }> = {
  ad: { one: "Ad", many: "Ads" },
  ad_group: { one: "Ad group", many: "Ad groups" },
  asset_group: { one: "Asset group", many: "Asset groups" },
  asset_group_link: { one: "Asset in an asset group", many: "Assets in asset groups" },
  brand_link: { one: "Business name or logo", many: "Business name and logos" },
  conversion_goal: { one: "Conversion goal", many: "Conversion goals" },
  language: { one: "Language", many: "Languages" },
  listing_filter: { one: "Product filter", many: "Product filters" },
  search_theme: { one: "Search theme", many: "Search themes" },
  text_asset: { one: "Text asset", many: "Text assets" },
  asset: { one: "Sitelink or callout", many: "Sitelinks and callouts" },
  asset_link: { one: "Sitelink or callout link", many: "Sitelink and callout links" },
  budget: { one: "Budget", many: "Budgets" },
  campaign: { one: "Campaign", many: "Campaigns" },
  excluded_location: { one: "Excluded location", many: "Excluded locations" },
  keyword: { one: "Keyword", many: "Keywords" },
  location: { one: "Location", many: "Locations" },
  negative_keyword: { one: "Negative keyword", many: "Negative keywords" },
}

function isKind(value: unknown): value is BuildKind {
  return typeof value === "string" && value in BUILD_KIND_LABELS
}

function text(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function count(value: unknown): number {
  return typeof value === "number" ? value : 0
}

/** Reads a campaign or ad group build result; null when malformed. */
export function parseCampaignBuildResult(value: unknown): CampaignBuildResult | null {
  if (!isRecord(value) || !Array.isArray(value["kinds"])) return null
  const requestedStatus = value["requested_status"]
  if (requestedStatus !== "PAUSED" && requestedStatus !== "ENABLED") return null
  const kinds: BuildKindCount[] = []
  for (const item of value["kinds"]) {
    if (!isRecord(item) || !isKind(item["kind"])) return null
    kinds.push({
      created: count(item["created"]),
      failed: count(item["failed"]),
      kind: item["kind"],
      unverified: count(item["unverified"]),
    })
  }
  const problems = (Array.isArray(value["problems"]) ? value["problems"] : []).flatMap(
    (item): BuildProblem[] =>
      isRecord(item) && isKind(item["kind"]) && isNonEmptyString(item["message"])
        ? [{ item: text(item["item"]), kind: item["kind"], message: item["message"] }]
        : []
  )
  return {
    campaignName: text(value["campaign_name"]),
    kinds,
    problems,
    requestedStatus,
  }
}

function total(result: CampaignBuildResult, field: "created" | "failed" | "unverified"): number {
  return result.kinds.reduce((sum, kind) => sum + kind[field], 0)
}

export function nothingCreated(result: CampaignBuildResult): boolean {
  return total(result, "created") === 0 && total(result, "unverified") === 0
}

export function hasFailures(result: CampaignBuildResult): boolean {
  return total(result, "failed") > 0
}

export function hasUnverified(result: CampaignBuildResult): boolean {
  return total(result, "unverified") > 0
}

export function campaignBuildSummary(result: CampaignBuildResult): string {
  if (nothingCreated(result)) return "nothing created"
  const number = (value: number) => value.toLocaleString("en-GB")
  const state = result.requestedStatus === "ENABLED" ? "active" : "paused"
  const created = total(result, "created")
  const failed = total(result, "failed")
  const unverified = total(result, "unverified")
  return [
    created ? `${number(created)} created, ${state}` : null,
    failed ? `${number(failed)} failed` : null,
    unverified ? `${number(unverified)} unconfirmed` : null,
  ]
    .filter(Boolean)
    .join(" · ")
}
