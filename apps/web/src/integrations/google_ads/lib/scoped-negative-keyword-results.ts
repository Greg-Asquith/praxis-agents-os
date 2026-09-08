// apps/web/src/integrations/google_ads/lib/scoped-negative-keyword-results.ts

import { googleAdsId } from "@/integrations/google_ads/lib/field-values"
import { parseKeywordRow } from "@/integrations/google_ads/lib/negative-keywords"
import { isNonNegativeInteger, isOneOf, isRecord } from "@/lib/guards"

type Counts = { applied: number; skipped: number; failed: number }
const COUNT_KEYS = ["applied", "skipped", "failed"] as const

export function parseScopedNegativeKeywordResult<T extends { identity: string }>(
  value: unknown,
  removing: boolean,
  collectionKey: string,
  errorsKey: string,
  parseIdentity: (value: Record<string, unknown>) => T | null
) {
  if (!isRecord(value)) return null
  const totals = parseCounts(value["counts"], removing)
  const items = value[collectionKey]
  const truncated = value[`${collectionKey}_truncated`]
  if (!totals || !Array.isArray(items) || typeof truncated !== "boolean") return null
  const rows = []
  const identities = new Set<string>()
  const sampled: Counts = { applied: 0, skipped: 0, failed: 0 }
  for (const item of items) {
    if (!isRecord(item)) return null
    const identity = parseIdentity(item)
    const evidence = parseTarget(item, removing, errorsKey)
    if (!identity || identities.has(identity.identity) || !evidence) return null
    identities.add(identity.identity)
    for (const key of COUNT_KEYS) sampled[key] += evidence.counts[key]
    rows.push({ ...identity, ...evidence })
  }
  if (!countsFit(sampled, totals, truncated)) return null
  return { rows, totals, truncated }
}

export function campaignNegativeKeywordIdentity(value: Record<string, unknown>) {
  const campaignId = googleAdsId(value["campaign_id"])
  const campaignName = value["campaign_name"]
  return campaignId && typeof campaignName === "string"
    ? { identity: campaignId, campaignId, campaignName }
    : null
}

export function adGroupNegativeKeywordIdentity(value: Record<string, unknown>) {
  const adGroupId = googleAdsId(value["ad_group_id"])
  const adGroupName = value["ad_group_name"]
  const campaignName = value["campaign_name"]
  return adGroupId && typeof adGroupName === "string" && typeof campaignName === "string"
    ? { identity: adGroupId, adGroupId, adGroupName, campaignName }
    : null
}

function parseCounts(value: unknown, removing: boolean): Counts | null {
  if (!isRecord(value)) return null
  const applied = value[removing ? "removed" : "added"]
  const skipped = value[removing ? "not_found" : "skipped_existing"]
  const failed = value["failed"]
  if (
    !isNonNegativeInteger(applied) ||
    !isNonNegativeInteger(skipped) ||
    !isNonNegativeInteger(failed)
  )
    return null
  if (![applied, skipped, failed].every(Number.isSafeInteger)) return null
  return { applied, skipped, failed }
}

function countsFit(sample: Counts, total: Counts, truncated: boolean) {
  return COUNT_KEYS.every(
    (key) => sample[key] <= total[key] && (truncated || sample[key] === total[key])
  )
}

function parseTarget(item: Record<string, unknown>, removing: boolean, errorsKey: string) {
  const counts = parseCounts(item["counts"], removing)
  const errorsTruncated = item["errors_truncated"]
  const errors = parseErrors(item[errorsKey], removing)
  if (!counts || typeof errorsTruncated !== "boolean" || !errors) return null
  if (errors.length > counts.failed || (!errorsTruncated && errors.length !== counts.failed))
    return null
  const rawOutcomes = item["keyword_outcomes"]
  const keywordOutcomes =
    rawOutcomes === undefined ? null : parseOutcomes(rawOutcomes, removing, counts)
  if (rawOutcomes !== undefined && !keywordOutcomes) return null
  return { counts, errors, errorsTruncated, keywordOutcomes }
}

function parseErrors(value: unknown, removing: boolean) {
  if (!Array.isArray(value)) return null
  const errors = []
  for (const item of value) {
    const keyword = parseKeywordRow(item, removing)
    if (
      !keyword?.text.trim() ||
      !isRecord(item) ||
      typeof item["message"] !== "string" ||
      typeof item["error_code"] !== "string"
    )
      return null
    errors.push({ ...keyword, message: item["message"], errorCode: item["error_code"] })
  }
  return errors
}

function parseOutcomes(value: unknown, removing: boolean, counts: Counts) {
  if (!Array.isArray(value)) return null
  const applied = removing ? "removed" : "added"
  const skipped = removing ? "not_found" : "skipped_existing"
  const tokens = new Set([applied, skipped, "failed"] as const)
  const outcomes = []
  const identities = new Set<string>()
  const exact: Counts = { applied: 0, skipped: 0, failed: 0 }
  for (const item of value) {
    if (!isRecord(item)) return null
    const outcome = item["outcome"]
    if (!isOneOf(tokens, outcome)) return null
    const keyword = parseKeywordRow(item, outcome === "not_found")
    if (!keyword?.text.trim()) return null
    const identity = JSON.stringify([keyword.text.toLowerCase(), keyword.matchType])
    if (identities.has(identity)) return null
    identities.add(identity)
    if (
      !(item["external_ref"] === undefined || typeof item["external_ref"] === "string") ||
      !(item["error_code"] === undefined || typeof item["error_code"] === "string")
    )
      return null
    exact[outcome === applied ? "applied" : outcome === skipped ? "skipped" : "failed"] += 1
    outcomes.push({
      ...keyword,
      outcome,
      ...(typeof item["external_ref"] === "string" ? { externalRef: item["external_ref"] } : {}),
      ...(typeof item["error_code"] === "string" ? { errorCode: item["error_code"] } : {}),
    })
  }
  return countsFit(exact, counts, false) ? outcomes : null
}
