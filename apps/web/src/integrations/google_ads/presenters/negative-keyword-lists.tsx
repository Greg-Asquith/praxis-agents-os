// apps/web/src/integrations/google_ads/presenters/negative-keyword-lists.tsx

import {
  NegativeKeywordListOutcome,
  type NegativeKeywordListError,
  type NegativeKeywordListResult,
} from "@/integrations/google_ads/components/negative-keyword-list-outcome"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"
import { isRecord } from "@/lib/guards"

export const googleAdsNegativeKeywordListsPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-create-negative-keyword-list",
  variants: {
    google_ads_create_negative_keyword_list: defineGoogleAdsWriteVariant({
      approval: {
        approveLabel: "Approve & Create",
        label: "Create Google Ads Negative Keyword Lists",
        parseArgs: negativeKeywordListArgs,
        prompt: "Review the list names before creating them in the selected accounts.",
        title: "Create Negative Keyword Lists",
      },
      deniedDescription: "This negative keyword list creation was declined. Nothing was created.",
      emptyLabel: "No Google Ads accounts created a negative keyword list.",
      failedDescription:
        "The update did not finish. No negative keyword list creation was confirmed.",
      heading: "Create Negative Keyword Lists",
      malformedDescription:
        "The system couldn't verify this account's negative keyword list outcomes. Check the Google Ads platform before taking further action.",
      parseResult: negativeKeywordListResult,
      progressLabel: "Creating Google Ads negative keyword lists…",
      renderOutcome: (result) => <NegativeKeywordListOutcome result={result} />,
      resultAriaLabel: "Google Ads negative keyword list results",
      resultFailure:
        "The system couldn't verify the negative keyword list changes. Check the Google Ads platform before taking further action.",
      unconfirmedAriaLabel: "Unconfirmed Google Ads negative keyword list update",
      unverifiedDescription:
        "The system couldn't verify whether Google Ads created these negative keyword lists. Check the Google Ads platform before taking further action.",
      waitingLabel: "Waiting for negative keyword list approval…",
    }),
  },
})

function negativeKeywordListArgs(value: unknown): Record<string, unknown> | null {
  return isRecord(value) &&
    Array.isArray(value["names"]) &&
    value["names"].length > 0 &&
    value["names"].every((name) => typeof name === "string" && name.trim().length > 0)
    ? value
    : null
}

function negativeKeywordListResult(value: unknown): NegativeKeywordListResult | null {
  if (!isRecord(value) || !Array.isArray(value["outcomes"])) {
    return null
  }
  const errors: NegativeKeywordListError[] = []
  const createdNames: string[] = []
  const skippedNames: string[] = []
  for (const item of value["outcomes"]) {
    if (
      !isRecord(item) ||
      typeof item["name"] !== "string" ||
      !["created", "already_exists", "failed"].includes(String(item["outcome"]))
    ) {
      return null
    }
    if (item["outcome"] === "created") {
      createdNames.push(item["name"])
    } else if (item["outcome"] === "already_exists") {
      skippedNames.push(item["name"])
    } else {
      errors.push({
        errorCode: typeof item["error_code"] === "string" ? item["error_code"] : "",
        message: typeof item["message"] === "string" ? item["message"] : "Creation failed.",
        name: item["name"],
      })
    }
  }
  return {
    createdNames,
    errors,
    skippedNames,
  }
}
