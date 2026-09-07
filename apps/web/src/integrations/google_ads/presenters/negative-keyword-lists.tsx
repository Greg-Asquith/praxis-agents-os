// apps/web/src/integrations/google_ads/presenters/negative-keyword-lists.tsx

import {
  GoogleAdsOutcomeTable,
  type GoogleAdsOutcomeRow,
} from "@/integrations/google_ads/components/outcome-table"
import { parseOutcomeList } from "@/integrations/google_ads/lib/envelopes"
import { countByKind } from "@/integrations/google_ads/lib/outcomes"
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
      renderOutcome: (rows) => (
        <GoogleAdsOutcomeTable
          columns={[{ key: "name", kind: "text", label: "Name" }]}
          rows={rows}
          outcomes={countByKind(rows)}
          exportFilename="google-ads-negative-keyword-lists.csv"
        />
      ),
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

function negativeKeywordListResult(value: unknown) {
  return parseOutcomeList(value, "outcomes", negativeKeywordListRow, (row) => row.name)
}

function negativeKeywordListRow(value: unknown): (GoogleAdsOutcomeRow & { name: string }) | null {
  if (
    !isRecord(value) ||
    typeof value["name"] !== "string" ||
    (value["outcome"] !== "created" &&
      value["outcome"] !== "already_exists" &&
      value["outcome"] !== "failed")
  )
    return null
  return {
    name: value["name"],
    outcome: value["outcome"],
    details:
      value["outcome"] === "failed"
        ? typeof value["message"] === "string"
          ? value["message"]
          : "Creation failed."
        : "",
    errorCode:
      value["outcome"] === "failed" && typeof value["error_code"] === "string"
        ? value["error_code"]
        : "",
  }
}
