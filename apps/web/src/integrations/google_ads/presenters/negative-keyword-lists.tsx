// apps/web/src/integrations/google_ads/presenters/negative-keyword-lists.tsx

import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import type { ToolRowPresenter } from "@/integrations/contract"
import {
  NegativeKeywordListOutcome,
  type NegativeKeywordListError,
  type NegativeKeywordListResult,
} from "@/integrations/google_ads/components/negative-keyword-list-outcome"
import { GoogleAdsToolHeading } from "@/integrations/google_ads/components/tool-heading"
import { formatGoogleAdsAccountId } from "@/lib/format"
import { isRecord } from "@/lib/guards"

export const googleAdsNegativeKeywordListsPresenter: ToolRowPresenter = {
  key: "google-ads-create-negative-keyword-list",
  matches: (activity) =>
    activity.name === "google_ads_create_negative_keyword_list" &&
    (activity.status === "running" || activity.status === "completed"),
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return (
        <FanOutSkeleton
          heading={<GoogleAdsToolHeading>Create Negative Keyword Lists</GoogleAdsToolHeading>}
          label="Creating Google Ads negative keyword lists…"
        />
      )
    }
    const fanOut = parseFanOutData(activity.result, negativeKeywordListResult)
    if (!fanOut) {
      return null
    }
    return (
      <div aria-label="Google Ads negative keyword list results" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Account"
          defaultOpen={defaultOpen}
          entries={fanOut.entries}
          emptyLabel="No Google Ads accounts created a negative keyword list."
          externalLabel="Customer ID"
          formatContextValue={formatGoogleAdsAccountId}
          heading={<GoogleAdsToolHeading>Create Negative Keyword Lists</GoogleAdsToolHeading>}
        >
          {(_entry, index) => {
            const result = fanOut.data[index]
            return result ? <NegativeKeywordListOutcome result={result} /> : null
          }}
        </FanOutShell>
      </div>
    )
  },
}

function negativeKeywordListResult(value: unknown): NegativeKeywordListResult | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["created_names"]) ||
    !value["created_names"].every((item) => typeof item === "string") ||
    !Array.isArray(value["resource_names"]) ||
    !value["resource_names"].every((item) => typeof item === "string") ||
    !Array.isArray(value["skipped_existing"]) ||
    !value["skipped_existing"].every((item) => typeof item === "string") ||
    !Array.isArray(value["list_errors"])
  ) {
    return null
  }
  const errors: NegativeKeywordListError[] = []
  for (const item of value["list_errors"]) {
    if (
      !isRecord(item) ||
      typeof item["name"] !== "string" ||
      typeof item["message"] !== "string"
    ) {
      return null
    }
    errors.push({
      errorCode:
        typeof item["error_code"] === "string"
          ? item["error_code"]
          : JSON.stringify(item["error_code"] ?? ""),
      message: item["message"],
      name: item["name"],
    })
  }
  return {
    createdNames: value["created_names"],
    errors,
    skippedNames: value["skipped_existing"],
  }
}
