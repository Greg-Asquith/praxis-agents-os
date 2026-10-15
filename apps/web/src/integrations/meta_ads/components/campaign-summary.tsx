// apps/web/src/integrations/meta_ads/components/campaign-summary.tsx

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { MetaAdsApprovalSection } from "@/integrations/meta_ads/components/approval-section"
import { OutcomeLink } from "@/integrations/meta_ads/components/create-ads"
import { LabelledInput } from "@/integrations/meta_ads/components/editor-fields"
import { MetaAdsOutcomeTable } from "@/integrations/meta_ads/components/outcome-table"
import { adsManagerObjectUrl } from "@/integrations/meta_ads/lib/ads-manager-link"
import {
  campaignSummary,
  PAUSED_NOTE,
  type CreateCampaignArgs,
  type CreateCampaignResult,
} from "@/integrations/meta_ads/lib/create-campaign"

export function CreateCampaignApproval({
  args,
  disabled,
  onFieldEdit,
}: {
  args: CreateCampaignArgs
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const { budget } = args
  return (
    <div className="grid min-w-0 gap-3">
      <MetaAdsApprovalSection ariaLabel="Campaign Summary" warning={PAUSED_NOTE}>
        <dl className="grid min-w-0 gap-2 text-sm sm:grid-cols-[8rem_minmax(0,1fr)]">
          {campaignSummary(args).map((line) => (
            <div className="contents" key={line.label}>
              <dt className="text-muted-foreground font-medium">{line.label}</dt>
              <dd className="grid min-w-0 gap-0.5 wrap-anywhere">
                {line.sentences.map((sentence) => (
                  <p key={sentence}>{sentence}</p>
                ))}
              </dd>
            </div>
          ))}
        </dl>
      </MetaAdsApprovalSection>
      <p className="text-muted-foreground text-xs">
        To change the objective, budget type, bidding, or special category, decline and ask the
        agent.
      </p>
      {budget.mode === "ad_set" ? null : (
        <div className="grid min-w-0 gap-3 sm:grid-cols-3">
          <LabelledInput
            disabled={disabled}
            id="meta-ads-campaign-budget"
            label={budget.mode === "campaign_daily" ? "Daily Budget" : "Lifetime Budget"}
            onChange={(amount) => {
              onFieldEdit("budget", { mode: budget.mode, amount: amount.trim() })
            }}
            value={budget.amount ?? ""}
          />
        </div>
      )}
    </div>
  )
}

export function CreateCampaignOutcome({ result }: { result: CreateCampaignResult }) {
  const { campaign } = result
  const manager = campaign.campaignId
    ? adsManagerObjectUrl("campaign", result.accountId, campaign.campaignId)
    : null
  return (
    <div className="grid gap-3">
      <MetaAdsOutcomeTable
        columns={[
          { key: "name", kind: "text", label: "Campaign" },
          { key: "links", kind: "text", label: "Links" },
        ]}
        exportFilename="meta-ads-created-campaign.csv"
        renderCell={(column) =>
          column.key === "links" && manager ? (
            <OutcomeLink href={manager}>Open in Ads Manager</OutcomeLink>
          ) : null
        }
        rows={[
          {
            name: campaign.name,
            links: "",
            outcome: campaign.outcome,
            details: [
              campaign.message,
              campaign.recovered
                ? "Meta's reply was lost, so the campaign was found by its name."
                : null,
            ]
              .filter(Boolean)
              .join(" "),
            errorCode: campaign.errorCode,
          },
        ]}
      />
      {campaign.outcome === "created" ? (
        <p className="text-sm">
          The campaign is paused. Ask the agent to create ad sets and ads in it, then turn it on.
        </p>
      ) : null}
    </div>
  )
}
