// apps/web/src/integrations/google_ads/presenters/negative-keywords/presenter.tsx

import type { ReactNode } from "react"

import { mergeApprovalArgs } from "@/components/tool-ui/approval-args"
import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"
import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import type { ToolRowPresenter } from "@/integrations/contract"
import { GoogleAdsLogo } from "@/integrations/google_ads/components/logo"
import { GoogleAdsToolHeading } from "@/integrations/google_ads/components/tool-heading"
import { formatGoogleAdsAccountId } from "@/lib/format"

type PresenterCopy = {
  approvalLabel: { add: string; remove: string }
  approvalPrompt: { add: string; remove: string }
  approvalTitle: { add: string; remove: string }
  deniedDescription: { add: string; remove: string }
  emptyLabel: string
  failedDescription: string
  heading: string
  progressLabel: { add: string; remove: string }
  resultAriaLabel: string
  resultFailure: string
  unconfirmedAriaLabel: string
  waitingLabel: string
}

type NegativeKeywordPresenterConfig<Args, Summary, Result> = {
  copy: PresenterCopy
  key: string
  parseArgs: (value: unknown, removing: boolean) => Args | null
  parseResult: (value: unknown, removing: boolean) => Result | null
  renderApprovalSummary: (summary: Summary) => ReactNode
  renderOutcome: (result: Result, removing: boolean) => ReactNode
  summarize: (value: unknown, fallback: Args) => Summary
  toolNames: { add: string; remove: string }
}

export function createNegativeKeywordPresenter<Args, Summary, Result>(
  config: NegativeKeywordPresenterConfig<Args, Summary, Result>
): ToolRowPresenter {
  return {
    handlesApprovals: true,
    key: config.key,
    matches: (activity) =>
      activity.name === config.toolNames.add || activity.name === config.toolNames.remove,
    render: ({ activity, approvalDecision, defaultOpen, ui }) => {
      const removing = activity.name === config.toolNames.remove
      const action = removing ? "remove" : "add"
      const originalArgs = config.parseArgs(activity.args, removing)
      if (approvalDecision) {
        if (!originalArgs) {
          return null
        }
        const summary = config.summarize(
          mergeApprovalArgs(activity.args, approvalDecision.decision.edits),
          originalArgs
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
            label={config.copy.approvalLabel[action]}
            prompt={config.copy.approvalPrompt[action]}
            title={config.copy.approvalTitle[action]}
            toolName={activity.name}
          >
            {config.renderApprovalSummary(summary)}
          </ToolApprovalDecisionCard>
        )
      }
      if (activity.status === "running" || activity.status === "awaiting_approval") {
        return (
          <FanOutSkeleton
            heading={<GoogleAdsToolHeading>{config.copy.heading}</GoogleAdsToolHeading>}
            label={
              activity.status === "awaiting_approval"
                ? config.copy.waitingLabel
                : config.copy.progressLabel[action]
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
            ? config.copy.deniedDescription[action]
            : config.copy.failedDescription
        return failure(activity.id, description, defaultOpen, config.copy)
      }
      const fanOut = parseFanOutData<Result>(activity.result, (value) =>
        config.parseResult(value, removing)
      )
      if (!fanOut) {
        return failure(activity.id, config.copy.resultFailure, defaultOpen, config.copy)
      }
      return (
        <div aria-label={config.copy.resultAriaLabel} className="w-full min-w-0">
          <FanOutShell
            contextLabel="Account"
            defaultOpen={defaultOpen}
            entries={fanOut.entries}
            emptyLabel={config.copy.emptyLabel}
            externalLabel="Customer ID"
            formatContextValue={formatGoogleAdsAccountId}
            heading={<GoogleAdsToolHeading>{config.copy.heading}</GoogleAdsToolHeading>}
          >
            {(_entry, index) => {
              const result = fanOut.data[index]
              return result ? config.renderOutcome(result, removing) : null
            }}
          </FanOutShell>
        </div>
      )
    },
  }
}

function failure(
  activityId: string,
  description: string,
  defaultOpen: boolean,
  copy: PresenterCopy
) {
  return (
    <div aria-label={copy.unconfirmedAriaLabel} className="w-full min-w-0">
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
        heading={<GoogleAdsToolHeading>{copy.heading}</GoogleAdsToolHeading>}
        renderFailed={() => <p className="text-destructive text-sm">{description}</p>}
      >
        {() => null}
      </FanOutShell>
    </div>
  )
}
