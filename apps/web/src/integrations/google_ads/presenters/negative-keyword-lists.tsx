// apps/web/src/integrations/google_ads/presenters/negative-keyword-lists.tsx

import { GoogleAdsApprovalSection } from "@/integrations/google_ads/components/approval-section"
import { GoogleAdsEntityCard } from "@/integrations/google_ads/components/entity-card"
import {
  GoogleAdsOutcomeTable,
  type GoogleAdsOutcomeRow,
} from "@/integrations/google_ads/components/outcome-table"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { parseOutcomeList } from "@/integrations/google_ads/lib/envelopes"
import { countByKind } from "@/integrations/google_ads/lib/outcomes"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"
import { isRecord } from "@/lib/guards"

export const googleAdsNegativeKeywordListsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_create_negative_keyword_list: defineIntegrationWriteVariant(googleAdsProvider, {
      copy: { verb: "Create", object: "negative keyword lists", effect: "created" },
      approval: {
        parseArgs: negativeKeywordListArgs,
        renderSummary: (value, fallback) => {
          const args = negativeKeywordListArgs(value) ?? fallback
          return (
            <GoogleAdsApprovalSection
              ariaLabel="Proposed negative keyword lists"
              countLine={approvalCountLine(args.names.length, "list")}
            >
              {args.names.map((name, index) => (
                <GoogleAdsEntityCard key={`${String(index)}:${name}`} title={name} />
              ))}
            </GoogleAdsApprovalSection>
          )
        },
        prompt: "Review the list names before creating them in the selected accounts.",
      },
      parseResult: negativeKeywordListResult,
      renderOutcome: (rows) => (
        <GoogleAdsOutcomeTable
          columns={[{ key: "name", kind: "text", label: "Name" }]}
          rows={rows}
          outcomes={countByKind(rows)}
          exportFilename="google-ads-negative-keyword-lists.csv"
        />
      ),
    }),
  },
})

function negativeKeywordListArgs(
  value: unknown
): (Record<string, unknown> & { names: string[] }) | null {
  return isRecord(value) &&
    Array.isArray(value["names"]) &&
    value["names"].length > 0 &&
    value["names"].every(
      (name): name is string => typeof name === "string" && name.trim().length > 0
    )
    ? { ...value, names: value["names"] }
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
