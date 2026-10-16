// apps/web/src/integrations/meta_ads/presenters/launch-campaign.tsx

import { mergeApprovalArgs } from "@/components/tool-ui/approval-args"
import { LaunchApproval } from "@/integrations/meta_ads/components/launch-summary"
import { LaunchOutcome } from "@/integrations/meta_ads/components/launch-outcome"
import { MetaAdsFailureTargets } from "@/integrations/meta_ads/components/outcome-table"
import {
  launchProblem,
  launchPrompt,
  parseLaunchArgs,
  type LaunchArgs,
} from "@/integrations/meta_ads/lib/launch-model"
import { parseLaunchResult, type LaunchResult } from "@/integrations/meta_ads/lib/launch-result"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import { editApprovalFields } from "@/integrations/approval-edits"
import type { ToolRowPresenterProps } from "@/integrations/contract"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"
import { isRecord } from "@/lib/guards"

function variant(approveLabel: string) {
  return defineIntegrationWriteVariant<LaunchArgs, LaunchResult>(metaAdsProvider, {
    copy: {
      verb: "Create",
      object: "campaign",
      effect: "built",
      check: "Check Ads Manager before launching this campaign again.",
    },
    heading: "Launch Meta Ads Campaign",
    progressLabel: "Building campaign…",
    waitingLabel: "Waiting for approval to build campaign…",
    approval: {
      approveLabel,
      label: "Launch Meta Ads Campaign",
      parseArgs: parseLaunchArgs,
      prompt: launchPrompt,
      title: (args) =>
        args.goLive ? `Launch ${args.campaign.name}` : `Build ${args.campaign.name} (paused)`,
      validateArgs: (value) => launchProblem(parseLaunchArgs(value)),
      renderInvalidDraft: true,
      renderSummary: (value, fallback, _onFieldEdit, disabled, controls) => (
        <LaunchApproval
          args={parseLaunchArgs(value) ?? fallback}
          disabled={disabled}
          onEdit={(edits) => {
            editApprovalFields(controls, disabled, edits)
          }}
        />
      ),
    },
    details: (args) => (args ? [{ label: "Campaign", value: args.campaign.name }] : []),
    parseResult: parseLaunchResult,
    settledPartial: (result) => result.state === "partial",
    settledUnverified: (result) =>
      result.state === "stopped" ||
      result.campaign.outcome === "unverified" ||
      result.adSets.some((adSet) => adSet.outcome === "unverified") ||
      result.ads.some((ad) => ad.outcome === "unverified"),
    settledFailure: (result) =>
      result.campaign.outcome === "failed" ? "Meta Ads didn't create this campaign." : null,
    renderFailure: (args, description, result) =>
      result ? (
        <div className="grid gap-3">
          <p className="text-destructive text-sm">{description}</p>
          <LaunchOutcome result={result} />
        </div>
      ) : (
        <MetaAdsFailureTargets
          description={description}
          targets={args ? [args.campaign.name] : []}
        />
      ),
    renderOutcome: (result) => <LaunchOutcome result={result} />,
    renderUnverifiedOutcome: (result) => <LaunchOutcome result={result} />,
  })
}

const build = variant("Approve & Build")
const launch = variant("Approve & Launch")

// The shared approval card takes one fixed label, so the label follows Go Live by picking a variant.
function launchRenderer(context: ToolRowPresenterProps) {
  const args = mergeApprovalArgs(
    context.activity.args,
    context.approvalDecision?.decision.edits ?? {}
  )
  return (isRecord(args) && args["go_live"] === true ? launch : build)(context)
}

export const metaAdsLaunchCampaignPresenter = createIntegrationWritePresenter({
  variants: { meta_ads_launch_campaign: launchRenderer },
})
