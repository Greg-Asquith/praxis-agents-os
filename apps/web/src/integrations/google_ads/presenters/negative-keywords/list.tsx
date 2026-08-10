// apps/web/src/integrations/google_ads/presenters/negative-keywords/list.tsx

import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import { mergeApprovalArgs } from "@/components/tool-ui/approval-args"
import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"
import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import type { ToolRowPresenter } from "@/integrations/contract"
import { GoogleAdsLogo } from "@/integrations/google_ads/components/logo"
import {
  NegativeKeywordApprovalSummary,
  NegativeKeywordOutcome,
  NegativeKeywordRemovalOutcome,
  type NegativeKeywordRemovalResult,
  type NegativeKeywordResult,
} from "@/integrations/google_ads/components/negative-keyword-outcome"
import { GoogleAdsToolHeading } from "@/integrations/google_ads/components/tool-heading"
import {
  listNegativeKeywordApprovalSummary,
  listNegativeKeywordArgs,
  listNegativeKeywordResult,
} from "@/integrations/google_ads/presenters/negative-keywords/utils"
import { formatGoogleAdsAccountId } from "@/lib/format"

export const googleAdsListNegativeKeywordsPresenter: ToolRowPresenter = {
  handlesApprovals: true,
  key: "google-ads-list-negative-keywords",
  matches: (activity) =>
    activity.name === "google_ads_add_negative_keywords" ||
    activity.name === "google_ads_remove_negative_keywords",
  render: ({ activity, approvalDecision, defaultOpen, ui }) => {
    const removing = activity.name === "google_ads_remove_negative_keywords"
    if (approvalDecision) {
      const originalArgs = listNegativeKeywordArgs(activity.args, removing)
      if (!originalArgs) {
        return null
      }
      const summary = listNegativeKeywordApprovalSummary(
        mergeApprovalArgs(activity.args, approvalDecision.decision.edits),
        originalArgs,
        removing
      )
      const fields = ui?.arg_fields ?? []
      return (
        <ToolApprovalDecisionCard
          activityId={activity.id}
          approveLabel={removing ? "Approve & Remove" : "Approve & Add"}
          args={activity.args}
          controls={approvalDecision}
          fallbackFields={approvalFallbackFields(activity.args, fields)}
          fields={fields}
          icon={<GoogleAdsLogo className="size-4" />}
          label={`${removing ? "Remove" : "Add"} Google Ads Negative Keywords`}
          prompt={
            removing
              ? "Review the target list and keyword rows. Removing them re-enables matching traffic."
              : "Review the target list and keyword rows before changing live ad delivery."
          }
          title={`${removing ? "Remove" : "Add"} Negative Keywords`}
          toolName={activity.name}
        >
          <NegativeKeywordApprovalSummary
            includeAny={removing}
            keywords={summary.keywords}
            listName={summary.listName}
            total={summary.total}
          />
        </ToolApprovalDecisionCard>
      )
    }
    if (activity.status === "running" || activity.status === "awaiting_approval") {
      return (
        <FanOutSkeleton
          heading={
            <GoogleAdsToolHeading>
              {removing ? "Remove Negative Keywords" : "Add Negative Keywords"}
            </GoogleAdsToolHeading>
          }
          label={
            activity.status === "awaiting_approval"
              ? "Waiting for negative keyword approval…"
              : `${removing ? "Removing" : "Adding"} Google Ads negative keywords…`
          }
        />
      )
    }
    if (
      activity.status === "denied" ||
      activity.status === "failed" ||
      activity.status === "unknown"
    ) {
      const description =
        activity.status === "denied"
          ? `This negative keyword change was declined. Nothing was ${removing ? "removed" : "added"}.`
          : "The update did not finish. No negative keyword change was confirmed."
      return failure(activity.id, description, defaultOpen, removing)
    }
    const fanOut = parseFanOutData<NegativeKeywordRemovalResult | NegativeKeywordResult>(
      activity.result,
      (value) => listNegativeKeywordResult(value, removing)
    )
    if (!fanOut) {
      return null
    }
    return (
      <div aria-label="Google Ads negative keyword results" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Account"
          defaultOpen={defaultOpen}
          entries={fanOut.entries}
          emptyLabel={`No Google Ads accounts ${removing ? "removed" : "added"} negative keywords.`}
          externalLabel="Customer ID"
          formatContextValue={formatGoogleAdsAccountId}
          heading={
            <GoogleAdsToolHeading>
              {removing ? "Remove Negative Keywords" : "Add Negative Keywords"}
            </GoogleAdsToolHeading>
          }
        >
          {(_entry, index) => {
            const result = fanOut.data[index]
            if (!result) {
              return null
            }
            return removing ? (
              <NegativeKeywordRemovalOutcome result={result as NegativeKeywordRemovalResult} />
            ) : (
              <NegativeKeywordOutcome result={result as NegativeKeywordResult} />
            )
          }}
        </FanOutShell>
      </div>
    )
  },
}

function failure(activityId: string, description: string, defaultOpen: boolean, removing: boolean) {
  return (
    <div aria-label="Unconfirmed Google Ads negative keyword update" className="w-full min-w-0">
      <FanOutShell
        contextLabel="Account"
        defaultOpen={defaultOpen}
        entries={[
          {
            connectionId: activityId,
            data: null,
            displayName: "Selected Google Ads account",
            errorMessage: description,
            externalId: "Selected Google Ads account",
            status: "failed",
          },
        ]}
        externalLabel="Customer ID"
        formatContextValue={formatGoogleAdsAccountId}
        heading={
          <GoogleAdsToolHeading>
            {removing ? "Remove Negative Keywords" : "Add Negative Keywords"}
          </GoogleAdsToolHeading>
        }
        renderFailed={() => <p className="text-destructive text-sm">{description}</p>}
      >
        {() => null}
      </FanOutShell>
    </div>
  )
}
