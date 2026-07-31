// apps/wev/src/integrations/google_ads/components/campaign-outcome.tsx

import { AlertCircleIcon, CircleCheckIcon } from "lucide-react"

import { KpiStrip } from "@/components/tool-ui/kpi"
import { Badge } from "@/components/ui/badge"
import { campaignReferenceLabels } from "@/integrations/google_ads/lib/tool-details"
import { titleCaseToken } from "@/lib/format"

export type CampaignError = {
  campaignId: string
  errorCode: string
  message: string
}

export type CampaignStatusResult = {
  errors: CampaignError[]
  succeededIds: string[]
}

export function CampaignOutcome({ result }: { result: CampaignStatusResult }) {
  return (
    <div className="grid min-w-0 gap-3">
      <KpiStrip
        items={[
          { label: "Succeeded", tone: "success", value: result.succeededIds.length },
          {
            label: "Failed",
            tone: result.errors.length > 0 ? "danger" : "neutral",
            value: result.errors.length,
          },
        ]}
      />
      <div className="grid gap-1" role="list">
        {result.succeededIds.map((campaignId) => (
          <div
            className="flex min-w-0 flex-wrap items-center gap-2 rounded-md px-2 py-2"
            key={`success:${campaignId}`}
            role="listitem"
          >
            <CircleCheckIcon className="text-success size-4" />
            <code className="min-w-0 flex-1 text-xs">{campaignId}</code>
            <Badge variant="success">Updated</Badge>
          </div>
        ))}
        {result.errors.map((error, index) => (
          <div
            className="bg-destructive/5 grid min-w-0 gap-1 rounded-md px-2 py-2"
            key={`failure:${error.campaignId}:${String(index)}`}
            role="listitem"
          >
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <AlertCircleIcon className="text-destructive size-4" />
              <code className="min-w-0 flex-1 text-xs">{error.campaignId || "Campaign"}</code>
              <Badge variant="destructive">Failed</Badge>
            </div>
            <p className="text-destructive pl-6 text-xs">{error.message}</p>
            {error.errorCode ? (
              <p className="text-muted-foreground pl-6 text-xs">
                {titleCaseToken(error.errorCode, error.errorCode)}
              </p>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  )
}

export function CampaignFailure({ args, description }: { args: unknown; description: string }) {
  return (
    <div className="grid gap-2">
      <p className="text-destructive text-sm">{description}</p>
      <CampaignIds args={args} />
    </div>
  )
}

function CampaignIds({ args }: { args: unknown }) {
  const campaigns = campaignReferenceLabels(args)
  return campaigns.length > 0 ? (
    <div className="flex flex-wrap gap-1">
      {campaigns.map((campaign) => (
        <code className="bg-muted rounded px-1.5 py-1 text-xs" key={campaign}>
          {campaign}
        </code>
      ))}
    </div>
  ) : null
}
