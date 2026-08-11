// apps/web/src/integrations/google_ads/presenters/negative-keywords/utils.tsx

import type {
  AdGroupNegativeKeywordResult,
  CampaignNegativeKeywordResult,
  NegativeKeyword,
  NegativeKeywordError,
  NegativeKeywordRemovalResult,
  NegativeKeywordResult,
  TargetNegativeKeywordOutcome,
} from "@/integrations/google_ads/components/negative-keyword-outcome"
import { isRecord } from "@/lib/guards"

export function listNegativeKeywordArgs(
  value: unknown,
  allowAny: boolean
): { keywords: NegativeKeyword[]; listName: string } | null {
  if (!isRecord(value) || !isRecord(value["negative_list"]) || !Array.isArray(value["keywords"])) {
    return null
  }
  const list = value["negative_list"]
  const listName =
    typeof list["label"] === "string" && list["label"].trim()
      ? list["label"].trim()
      : "Selected negative keyword list"
  const keywords: NegativeKeyword[] = []
  for (const item of value["keywords"]) {
    const keyword = parseKeyword(item, allowAny)
    if (!keyword) {
      return null
    }
    keywords.push(keyword)
  }
  return keywords.length > 0 ? { keywords, listName } : null
}

export function listNegativeKeywordApprovalSummary(
  value: unknown,
  fallback: { keywords: NegativeKeyword[]; listName: string },
  allowAny: boolean
): { keywords: NegativeKeyword[]; listName: string; total: number } {
  if (!isRecord(value)) {
    return { ...fallback, total: fallback.keywords.length }
  }
  const list = value["negative_list"]
  const listName =
    isRecord(list) && typeof list["label"] === "string" && list["label"].trim()
      ? list["label"].trim()
      : fallback.listName
  const rows = value["keywords"]
  if (!Array.isArray(rows)) {
    return { keywords: fallback.keywords, listName, total: fallback.keywords.length }
  }
  const keywords = rows.flatMap((row) => {
    const keyword = parseKeyword(row, allowAny)
    return keyword ? [keyword] : []
  })
  return { keywords, listName, total: rows.length }
}

export function listNegativeKeywordResult(
  value: unknown,
  removing: boolean
): NegativeKeywordRemovalResult | NegativeKeywordResult | null {
  return removing ? removalResult(value) : addResult(value)
}

export function campaignNegativeKeywordArgs(
  value: unknown,
  allowAny: boolean
): { campaignCount: number; keywordCount: number } | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["campaign_ids"]) ||
    value["campaign_ids"].length === 0 ||
    !Array.isArray(value["keywords"]) ||
    value["keywords"].length === 0 ||
    !value["campaign_ids"].every(
      (campaign) => isRecord(campaign) && typeof campaign["external_id"] === "string"
    ) ||
    !value["keywords"].every((keyword) => parseKeyword(keyword, allowAny) !== null)
  ) {
    return null
  }
  return {
    campaignCount: value["campaign_ids"].length,
    keywordCount: value["keywords"].length,
  }
}

export function campaignNegativeKeywordSummary(
  value: unknown,
  fallback: { campaignCount: number; keywordCount: number }
) {
  if (!isRecord(value)) {
    return fallback
  }
  return {
    campaignCount: Array.isArray(value["campaign_ids"])
      ? value["campaign_ids"].length
      : fallback.campaignCount,
    keywordCount: Array.isArray(value["keywords"])
      ? value["keywords"].length
      : fallback.keywordCount,
  }
}

export function campaignNegativeKeywordResult(
  value: unknown,
  removing: boolean
): CampaignNegativeKeywordResult | null {
  const appliedKey = removing ? "removed" : "added"
  const skippedKey = removing ? "not_found" : "skipped_existing"
  if (
    !isRecord(value) ||
    !isRecord(value["counts"]) ||
    !isOutcomeCount(value["counts"][appliedKey]) ||
    !isOutcomeCount(value["counts"][skippedKey]) ||
    !isOutcomeCount(value["counts"]["failed"]) ||
    !Array.isArray(value["campaigns"]) ||
    typeof value["campaigns_truncated"] !== "boolean"
  ) {
    return null
  }
  const campaigns = []
  for (const item of value["campaigns"]) {
    if (
      !isRecord(item) ||
      typeof item["campaign_id"] !== "string" ||
      typeof item["campaign_name"] !== "string" ||
      !isRecord(item["counts"]) ||
      !isOutcomeCount(item["counts"][appliedKey]) ||
      !isOutcomeCount(item["counts"][skippedKey]) ||
      !isOutcomeCount(item["counts"]["failed"]) ||
      !Array.isArray(item["campaign_errors"]) ||
      typeof item["errors_truncated"] !== "boolean"
    ) {
      return null
    }
    const errors = []
    for (const error of item["campaign_errors"]) {
      const keyword = parseKeyword(error, true)
      if (
        !keyword ||
        !isRecord(error) ||
        typeof error["message"] !== "string" ||
        typeof error["error_code"] !== "string"
      ) {
        return null
      }
      errors.push({
        ...keyword,
        errorCode: error["error_code"],
        message: error["message"],
      })
    }
    const keywordOutcomes = parseTargetKeywordOutcomes(item["keyword_outcomes"])
    if (item["keyword_outcomes"] !== undefined && keywordOutcomes === null) {
      return null
    }
    campaigns.push({
      campaignId: item["campaign_id"],
      campaignName: item["campaign_name"],
      counts: {
        applied: item["counts"][appliedKey],
        failed: item["counts"]["failed"],
        skipped: item["counts"][skippedKey],
      },
      errors,
      errorsTruncated: item["errors_truncated"],
      keywordOutcomes,
    })
  }
  return {
    campaigns,
    campaignsTruncated: value["campaigns_truncated"],
    totals: {
      applied: value["counts"][appliedKey],
      failed: value["counts"]["failed"],
      skipped: value["counts"][skippedKey],
    },
  }
}

export function adGroupNegativeKeywordArgs(
  value: unknown,
  allowAny: boolean
): { adGroupCount: number; keywordCount: number; selectionLabels: string[] } | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["ad_group_ids"]) ||
    value["ad_group_ids"].length === 0 ||
    !Array.isArray(value["keywords"]) ||
    value["keywords"].length === 0 ||
    !value["keywords"].every((keyword) => parseKeyword(keyword, allowAny) !== null)
  ) {
    return null
  }
  const selectionLabels: string[] = []
  for (const adGroup of value["ad_group_ids"]) {
    if (!isRecord(adGroup) || typeof adGroup["external_id"] !== "string") {
      return null
    }
    const label = typeof adGroup["label"] === "string" ? adGroup["label"].trim() : ""
    const scopeLabel =
      typeof adGroup["scope_label"] === "string" ? adGroup["scope_label"].trim() : ""
    selectionLabels.push(
      [label || `Ad group ${adGroup["external_id"]}`, scopeLabel].filter(Boolean).join(" — ")
    )
  }
  return {
    adGroupCount: value["ad_group_ids"].length,
    keywordCount: value["keywords"].length,
    selectionLabels,
  }
}

export function adGroupNegativeKeywordSummary(
  value: unknown,
  fallback: { adGroupCount: number; keywordCount: number; selectionLabels: string[] }
) {
  const parsed = adGroupNegativeKeywordArgs(value, true)
  if (parsed) {
    return parsed
  }
  if (!isRecord(value)) {
    return fallback
  }
  return {
    adGroupCount: Array.isArray(value["ad_group_ids"])
      ? value["ad_group_ids"].length
      : fallback.adGroupCount,
    keywordCount: Array.isArray(value["keywords"])
      ? value["keywords"].length
      : fallback.keywordCount,
    selectionLabels: fallback.selectionLabels,
  }
}

export function adGroupNegativeKeywordResult(
  value: unknown,
  removing: boolean
): AdGroupNegativeKeywordResult | null {
  const appliedKey = removing ? "removed" : "added"
  const skippedKey = removing ? "not_found" : "skipped_existing"
  if (
    !isRecord(value) ||
    !isRecord(value["counts"]) ||
    !isOutcomeCount(value["counts"][appliedKey]) ||
    !isOutcomeCount(value["counts"][skippedKey]) ||
    !isOutcomeCount(value["counts"]["failed"]) ||
    !Array.isArray(value["ad_groups"]) ||
    typeof value["ad_groups_truncated"] !== "boolean"
  ) {
    return null
  }
  const adGroups = []
  for (const item of value["ad_groups"]) {
    if (
      !isRecord(item) ||
      typeof item["ad_group_id"] !== "string" ||
      typeof item["ad_group_name"] !== "string" ||
      typeof item["campaign_name"] !== "string" ||
      !isRecord(item["counts"]) ||
      !isOutcomeCount(item["counts"][appliedKey]) ||
      !isOutcomeCount(item["counts"][skippedKey]) ||
      !isOutcomeCount(item["counts"]["failed"]) ||
      !Array.isArray(item["ad_group_errors"]) ||
      typeof item["errors_truncated"] !== "boolean"
    ) {
      return null
    }
    const errors = []
    for (const error of item["ad_group_errors"]) {
      const keyword = parseKeyword(error, true)
      if (
        !keyword ||
        !isRecord(error) ||
        typeof error["message"] !== "string" ||
        typeof error["error_code"] !== "string"
      ) {
        return null
      }
      errors.push({
        ...keyword,
        errorCode: error["error_code"],
        message: error["message"],
      })
    }
    const keywordOutcomes = parseTargetKeywordOutcomes(item["keyword_outcomes"])
    if (item["keyword_outcomes"] !== undefined && keywordOutcomes === null) {
      return null
    }
    adGroups.push({
      adGroupId: item["ad_group_id"],
      adGroupName: item["ad_group_name"],
      campaignName: item["campaign_name"],
      counts: {
        applied: item["counts"][appliedKey],
        failed: item["counts"]["failed"],
        skipped: item["counts"][skippedKey],
      },
      errors,
      errorsTruncated: item["errors_truncated"],
      keywordOutcomes,
    })
  }
  return {
    adGroups,
    adGroupsTruncated: value["ad_groups_truncated"],
    totals: {
      applied: value["counts"][appliedKey],
      failed: value["counts"]["failed"],
      skipped: value["counts"][skippedKey],
    },
  }
}

function addResult(value: unknown): NegativeKeywordResult | null {
  if (!isResultEnvelope(value, "added", "skipped_existing")) {
    return null
  }
  const addedKeywords: NegativeKeyword[] = []
  for (const item of value.samples.added) {
    const keyword = parseKeyword(item)
    if (!keyword || !isRecord(item) || typeof item["resource_name"] !== "string") {
      return null
    }
    addedKeywords.push(keyword)
  }
  const skippedExisting = parseKeywords(value.samples.skipped_existing)
  const errors = parseErrors(value.samples.failed)
  if (!skippedExisting || !errors) {
    return null
  }
  return {
    addedCount: value.counts.added,
    addedKeywords,
    errors,
    failedCount: value.counts.failed,
    samplesTruncated: value.samples_truncated,
    skippedCount: value.counts.skipped_existing,
    skippedExisting,
  }
}

function removalResult(value: unknown): NegativeKeywordRemovalResult | null {
  if (!isResultEnvelope(value, "removed", "not_found")) {
    return null
  }
  const removedKeywords: NegativeKeyword[] = []
  for (const item of value.samples.removed) {
    const keyword = parseKeyword(item)
    if (!keyword || !isRecord(item) || typeof item["resource_name"] !== "string") {
      return null
    }
    removedKeywords.push(keyword)
  }
  const notFound = parseKeywords(value.samples.not_found, true)
  const errors = parseErrors(value.samples.failed)
  if (!notFound || !errors) {
    return null
  }
  return {
    errors,
    failedCount: value.counts.failed,
    notFound,
    notFoundCount: value.counts.not_found,
    removedCount: value.counts.removed,
    removedKeywords,
    samplesTruncated: value.samples_truncated,
  }
}

function isResultEnvelope<
  AppliedKey extends "added" | "removed",
  SkippedKey extends "not_found" | "skipped_existing",
>(
  value: unknown,
  appliedKey: AppliedKey,
  skippedKey: SkippedKey
): value is {
  counts: Record<AppliedKey | SkippedKey | "failed", number>
  samples: Record<AppliedKey | SkippedKey | "failed", unknown[]>
  samples_truncated: boolean
} {
  return (
    isRecord(value) &&
    isRecord(value["counts"]) &&
    isRecord(value["samples"]) &&
    isOutcomeCount(value["counts"][appliedKey]) &&
    isOutcomeCount(value["counts"][skippedKey]) &&
    isOutcomeCount(value["counts"]["failed"]) &&
    Array.isArray(value["samples"][appliedKey]) &&
    Array.isArray(value["samples"][skippedKey]) &&
    Array.isArray(value["samples"]["failed"]) &&
    typeof value["samples_truncated"] === "boolean"
  )
}

function parseKeywords(values: unknown[], allowAny = false): NegativeKeyword[] | null {
  const keywords: NegativeKeyword[] = []
  for (const value of values) {
    const keyword = parseKeyword(value, allowAny)
    if (!keyword) {
      return null
    }
    keywords.push(keyword)
  }
  return keywords
}

function parseErrors(values: unknown[]): NegativeKeywordError[] | null {
  const errors: NegativeKeywordError[] = []
  for (const item of values) {
    if (
      !isRecord(item) ||
      typeof item["message"] !== "string" ||
      (item["scope"] !== "keyword" && item["scope"] !== "account")
    ) {
      return null
    }
    const details = {
      errorCode: typeof item["error_code"] === "string" ? item["error_code"] : "unknown",
      message: item["message"],
    }
    if (item["scope"] === "account") {
      errors.push({ ...details, scope: "account" })
      continue
    }
    const keyword = parseKeyword(item)
    if (!keyword) {
      return null
    }
    errors.push({ ...details, ...keyword, scope: "keyword" })
  }
  return errors
}

function isOutcomeCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
}

function parseKeyword(value: unknown, allowAny = false): NegativeKeyword | null {
  if (
    !isRecord(value) ||
    typeof value["text"] !== "string" ||
    (value["match_type"] !== "EXACT" &&
      value["match_type"] !== "PHRASE" &&
      value["match_type"] !== "BROAD" &&
      (!allowAny || value["match_type"] !== "ANY"))
  ) {
    return null
  }
  return { matchType: value["match_type"], text: value["text"] }
}

function parseTargetKeywordOutcomes(value: unknown): TargetNegativeKeywordOutcome[] | null {
  if (value === undefined) return null
  if (!Array.isArray(value)) return null
  const outcomes: TargetNegativeKeywordOutcome[] = []
  for (const item of value) {
    const keyword = parseKeyword(item, true)
    if (
      !keyword ||
      !isRecord(item) ||
      (item["outcome"] !== "added" &&
        item["outcome"] !== "removed" &&
        item["outcome"] !== "skipped_existing" &&
        item["outcome"] !== "not_found" &&
        item["outcome"] !== "failed") ||
      !(item["external_ref"] === undefined || typeof item["external_ref"] === "string") ||
      !(item["error_code"] === undefined || typeof item["error_code"] === "string")
    ) {
      return null
    }
    outcomes.push({
      ...keyword,
      ...(typeof item["error_code"] === "string" ? { errorCode: item["error_code"] } : {}),
      ...(typeof item["external_ref"] === "string" ? { externalRef: item["external_ref"] } : {}),
      outcome: item["outcome"],
    })
  }
  return outcomes
}
