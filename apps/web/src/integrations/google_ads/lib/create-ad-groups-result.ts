// apps/web/src/integrations/google_ads/lib/create-ad-groups-result.ts

import { isNonEmptyString, isRecord } from "@/lib/guards"

type BuildKind = "ad_group" | "keyword" | "negative_keyword" | "ad"

export type BuildKindCount = {
  created: number
  failed: number
  kind: BuildKind
  unverified: number
}

type BuildProblem = { item: string; kind: BuildKind; message: string }

export type CreateAdGroupsResult = {
  campaignName: string
  kinds: BuildKindCount[]
  problems: BuildProblem[]
  requestedStatus: "PAUSED" | "ENABLED"
}

export const BUILD_KIND_LABELS: Record<BuildKind, { one: string; many: string }> = {
  ad: { one: "Ad", many: "Ads" },
  ad_group: { one: "Ad group", many: "Ad groups" },
  keyword: { one: "Keyword", many: "Keywords" },
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

export function parseCreateAdGroupsResult(value: unknown): CreateAdGroupsResult | null {
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

function total(result: CreateAdGroupsResult, field: "created" | "failed" | "unverified"): number {
  return result.kinds.reduce((sum, kind) => sum + kind[field], 0)
}

export function nothingCreated(result: CreateAdGroupsResult): boolean {
  return total(result, "created") === 0 && total(result, "unverified") === 0
}

export function hasFailures(result: CreateAdGroupsResult): boolean {
  return total(result, "failed") > 0
}

export function hasUnverified(result: CreateAdGroupsResult): boolean {
  return total(result, "unverified") > 0
}

export function createAdGroupsSummary(result: CreateAdGroupsResult): string {
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
