// apps/web/src/integrations/meta_ads/components/launch-summary.tsx

import { useId, useState } from "react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { AutomaticChanges } from "@/integrations/meta_ads/components/automatic-changes"
import { CreateCampaignApproval } from "@/integrations/meta_ads/components/campaign-summary"
import { LaunchAdSetBlock, type SelectedAd } from "@/integrations/meta_ads/components/launch-ad-set"
import { SettingRow, SettingRows } from "@/integrations/meta_ads/components/setting-rows"
import { StatusChoice } from "@/integrations/meta_ads/components/status-choice"
import { UrlTagsRow } from "@/integrations/meta_ads/components/url-tags-row"
import { hasAiGeneratedChange } from "@/integrations/meta_ads/lib/automatic-changes"
import { adRows } from "@/integrations/meta_ads/lib/create-ads-checks"
import {
  campaignSummaries,
  createCampaignProblem,
} from "@/integrations/meta_ads/lib/create-campaign"
import {
  adSetProblem,
  adsEdit,
  campaignEdit,
  launchSettingEdit,
  spendLine,
  type LaunchArgs,
} from "@/integrations/meta_ads/lib/launch-model"
import { MediaAccountContext } from "@/integrations/meta_ads/lib/meta-pictures"

const adSetRowKey = (key: string) => `ad-set:${key}`

/** The whole launch on one card: spend, Go Live, the campaign, and each ad set with its ads. */
export function LaunchApproval({
  args,
  disabled,
  onEdit,
}: {
  args: LaunchArgs
  disabled: boolean
  onEdit: (edits: Record<string, EditedValue>) => void
}) {
  const id = useId()
  const rows = adRows(args.ads)
  const spend = spendLine(args)
  const aiOn = hasAiGeneratedChange(args.ads.catalogue, args.ads.enabledChanges)
  // Opens the first ad that needs attention, so a problem is on screen before approving.
  const [selected, setSelected] = useState<SelectedAd | null>(() => {
    const flagged = rows.find((row) => row.check === "error")
    const key = flagged?.ad.adSetIds[0]
    return flagged && key ? { key, index: flagged.ad.index } : null
  })
  const campaignProblem = createCampaignProblem(args.campaign)
  // Opens the first row that needs attention, or none.
  const firstProblem = campaignProblem
    ? "campaign"
    : (args.adSets.map((item) => item.key).find((key) => adSetProblem(args, key)) ?? null)
  const row = rows.find((item) => item.ad.index === selected?.index) ?? rows[0]
  return (
    <MediaAccountContext value={args.ads.accountId}>
      <div className="grid min-w-0 gap-4">
        <div className="grid min-w-0 gap-1">
          {args.accountName ? (
            <p className="truncate text-sm font-medium">{args.accountName}</p>
          ) : null}
          <p className="text-foreground/80 text-sm" role="note">
            {spend ?? "Set a budget to see the most this can spend."}
          </p>
        </div>
        <StatusChoice
          activeNote={
            aiOn
              ? "Turns on when built, but the ads start paused because an AI-generated setting is on. Check Meta's preview before turning them on."
              : "Turns on when built. Ads start once Meta approves them."
          }
          disabled={disabled}
          label="When Built"
          labels={{ paused: "Build Paused", active: "Launch" }}
          onChange={(choice) => {
            onEdit({ go_live: choice === "active" })
          }}
          pausedNote="Builds everything paused. Nothing spends until you turn it on."
          value={args.goLive ? "active" : "paused"}
        />
        <SettingRows
          ariaLabel="Launch settings"
          defaultOpen={campaignProblem ? "campaign" : firstProblem && adSetRowKey(firstProblem)}
        >
          <SettingRow
            rowKey="campaign"
            summary={campaignProblem ?? campaignSummaries(args.campaign).budget}
            title={args.campaign.name || "Unnamed campaign"}
            tone={campaignProblem ? "error" : "neutral"}
          >
            <CreateCampaignApproval
              args={args.campaign}
              disabled={disabled}
              embedded
              onEdit={(edits) => {
                onEdit(campaignEdit(args, edits))
              }}
            />
          </SettingRow>
          {args.adSets.map((adSet) => (
            <LaunchAdSetBlock
              key={adSet.key}
              args={args}
              disabled={disabled}
              keyOf={adSet.key}
              onEdit={onEdit}
              onSelect={setSelected}
              rowKey={adSetRowKey(adSet.key)}
              rows={rows}
              selected={selected}
            />
          ))}
          {row && !row.ad.post ? (
            <UrlTagsRow
              args={args.ads}
              disabled={disabled}
              id={id}
              onEdit={(ads) => {
                onEdit(adsEdit(ads))
              }}
              onEditSetting={(key, value) => {
                onEdit(launchSettingEdit(args, row.ad.index, key, value))
              }}
              row={row}
            />
          ) : null}
          <AutomaticChanges
            args={args.ads}
            disabled={disabled}
            onChange={(value) => {
              onEdit({ automatic_changes: value })
            }}
          />
        </SettingRows>
      </div>
    </MediaAccountContext>
  )
}
