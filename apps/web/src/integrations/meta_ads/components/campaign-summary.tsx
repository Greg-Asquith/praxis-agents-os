// apps/web/src/integrations/meta_ads/components/campaign-summary.tsx

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { CreateSummary } from "@/integrations/meta_ads/components/create-summary"
import { LabelledInput } from "@/integrations/meta_ads/components/editor-fields"
import {
  campaignSummary,
  type CreateCampaignArgs,
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
      <CreateSummary ariaLabel="Campaign Summary" lines={campaignSummary(args)} />
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
