// apps/web/src/integrations/google_ads/presenters/negative-keywords.tsx

import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"
import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import type { ToolRowPresenter } from "@/integrations/contract"
import { GoogleAdsLogo } from "@/integrations/google_ads/components/logo"
import {
  NegativeKeywordApprovalSummary,
  NegativeKeywordOutcome,
  type NegativeKeyword,
  type NegativeKeywordError,
  type NegativeKeywordResult,
} from "@/integrations/google_ads/components/negative-keyword-outcome"
import { GoogleAdsToolHeading } from "@/integrations/google_ads/components/tool-heading"
import { formatGoogleAdsAccountId } from "@/lib/format"
import { isRecord } from "@/lib/guards"

export const googleAdsNegativeKeywordsPresenter: ToolRowPresenter = {
  handlesApprovals: true,
  key: "google-ads-add-negative-keywords",
  matches: (activity) => activity.name === "google_ads_add_negative_keywords",
  render: ({ activity, approvalDecision, defaultOpen, ui }) => {
    if (approvalDecision) {
      const originalArgs = negativeKeywordArgs(activity.args)
      if (!originalArgs) {
        return null
      }
      const approvalSummary = negativeKeywordApprovalSummary(
        mergeApprovalArgs(activity.args, approvalDecision.decision.edits),
        originalArgs
      )
      const fields = ui?.arg_fields ?? []
      return (
        <ToolApprovalDecisionCard
          activityId={activity.id}
          approveLabel="Approve & Add"
          args={activity.args}
          controls={approvalDecision}
          fallbackFields={approvalFallbackFields(activity.args, fields)}
          fields={fields}
          icon={<GoogleAdsLogo className="size-4" />}
          label="Add Google Ads Negative Keywords"
          prompt="Review the target list and keyword rows before changing live ad delivery."
          title="Add Negative Keywords"
          toolName={activity.name}
        >
          <NegativeKeywordApprovalSummary
            keywords={approvalSummary.keywords}
            listName={approvalSummary.listName}
            total={approvalSummary.total}
          />
        </ToolApprovalDecisionCard>
      )
    }
    if (activity.status === "running") {
      return (
        <FanOutSkeleton
          heading={<GoogleAdsToolHeading>Add Negative Keywords</GoogleAdsToolHeading>}
          label="Adding Google Ads negative keywords…"
        />
      )
    }
    if (activity.status === "awaiting_approval") {
      return (
        <FanOutSkeleton
          heading={<GoogleAdsToolHeading>Add Negative Keywords</GoogleAdsToolHeading>}
          label="Waiting for negative keyword approval…"
        />
      )
    }
    if (activity.status === "denied") {
      return negativeKeywordFailure(
        activity.id,
        "This negative keyword change was declined. Nothing was added.",
        defaultOpen
      )
    }
    if (activity.status === "failed" || activity.status === "unknown") {
      return negativeKeywordFailure(
        activity.id,
        "The update did not finish. No negative keyword change was confirmed.",
        defaultOpen
      )
    }
    const fanOut = parseFanOutData(activity.result, negativeKeywordResult)
    if (!fanOut) {
      return null
    }
    return (
      <div aria-label="Google Ads negative keyword results" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Account"
          defaultOpen={defaultOpen}
          entries={fanOut.entries}
          emptyLabel="No Google Ads accounts added negative keywords."
          externalLabel="Customer ID"
          formatContextValue={formatGoogleAdsAccountId}
          heading={<GoogleAdsToolHeading>Add Negative Keywords</GoogleAdsToolHeading>}
        >
          {(_entry, index) => {
            const result = fanOut.data[index]
            return result ? <NegativeKeywordOutcome result={result} /> : null
          }}
        </FanOutShell>
      </div>
    )
  },
}

function negativeKeywordFailure(activityId: string, description: string, defaultOpen: boolean) {
  const entries = [
    {
      connectionId: activityId,
      data: null,
      displayName: "Selected Google Ads account",
      errorMessage: description,
      externalId: "Selected Google Ads account",
      status: "failed",
    },
  ]
  return (
    <div aria-label="Unconfirmed Google Ads negative keyword update" className="w-full min-w-0">
      <FanOutShell
        contextLabel="Account"
        defaultOpen={defaultOpen}
        entries={entries}
        externalLabel="Customer ID"
        formatContextValue={formatGoogleAdsAccountId}
        heading={<GoogleAdsToolHeading>Add Negative Keywords</GoogleAdsToolHeading>}
        renderFailed={() => <p className="text-destructive text-sm">{description}</p>}
      >
        {() => null}
      </FanOutShell>
    </div>
  )
}

function negativeKeywordArgs(
  value: unknown
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
    const keyword = parseKeyword(item)
    if (!keyword) {
      return null
    }
    keywords.push(keyword)
  }
  return keywords.length > 0 ? { keywords, listName } : null
}

function negativeKeywordApprovalSummary(
  value: unknown,
  fallback: { keywords: NegativeKeyword[]; listName: string }
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
  const keywords: NegativeKeyword[] = []
  for (const row of rows) {
    const matchType = isRecord(row) ? row["match_type"] : null
    if (
      !isRecord(row) ||
      (matchType !== "EXACT" && matchType !== "PHRASE" && matchType !== "BROAD")
    ) {
      continue
    }
    keywords.push({
      matchType,
      text: typeof row["text"] === "string" ? row["text"] : "",
    })
  }
  return { keywords, listName, total: rows.length }
}

function negativeKeywordResult(value: unknown): NegativeKeywordResult | null {
  if (!isRecord(value)) {
    return null
  }
  const counts = value["counts"]
  const samples = value["samples"]
  if (
    !isRecord(counts) ||
    !isRecord(samples) ||
    !isOutcomeCount(counts["added"]) ||
    !isOutcomeCount(counts["skipped_existing"]) ||
    !isOutcomeCount(counts["failed"]) ||
    !Array.isArray(samples["added"]) ||
    !Array.isArray(samples["skipped_existing"]) ||
    !Array.isArray(samples["failed"]) ||
    typeof value["samples_truncated"] !== "boolean"
  ) {
    return null
  }
  const addedKeywords: NegativeKeyword[] = []
  for (const item of samples["added"]) {
    const keyword = parseKeyword(item)
    if (!keyword || !isRecord(item) || typeof item["resource_name"] !== "string") {
      return null
    }
    addedKeywords.push(keyword)
  }
  const skippedExisting: NegativeKeyword[] = []
  for (const item of samples["skipped_existing"]) {
    const keyword = parseKeyword(item)
    if (!keyword) {
      return null
    }
    skippedExisting.push(keyword)
  }
  const errors: NegativeKeywordError[] = []
  for (const item of samples["failed"]) {
    if (
      !isRecord(item) ||
      typeof item["message"] !== "string" ||
      (item["scope"] !== "keyword" && item["scope"] !== "account")
    ) {
      return null
    }
    const errorDetails = {
      errorCode: typeof item["error_code"] === "string" ? item["error_code"] : "unknown",
      message: item["message"],
    }
    if (item["scope"] === "account") {
      errors.push({ ...errorDetails, scope: "account" })
      continue
    }
    const keyword = parseKeyword(item)
    if (!keyword) {
      return null
    }
    errors.push({ ...errorDetails, ...keyword, scope: "keyword" })
  }
  return {
    addedCount: counts["added"],
    addedKeywords,
    errors,
    failedCount: counts["failed"],
    samplesTruncated: value["samples_truncated"],
    skippedCount: counts["skipped_existing"],
    skippedExisting,
  }
}

function isOutcomeCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
}

function mergeApprovalArgs(args: unknown, edits: Record<string, unknown>): unknown {
  return isRecord(args) ? { ...args, ...edits } : args
}

function parseKeyword(value: unknown): NegativeKeyword | null {
  if (
    !isRecord(value) ||
    typeof value["text"] !== "string" ||
    (value["match_type"] !== "EXACT" &&
      value["match_type"] !== "PHRASE" &&
      value["match_type"] !== "BROAD")
  ) {
    return null
  }
  return { matchType: value["match_type"], text: value["text"] }
}
