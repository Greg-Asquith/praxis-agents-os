// apps/web/src/integrations/meta_ads/components/campaign-edits.tsx

import { TriangleAlertIcon } from "lucide-react"
import { useId, type ReactNode } from "react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { ChoiceCards, SwitchField } from "@/integrations/meta_ads/components/campaign-controls"
import { MoneyField } from "@/integrations/meta_ads/components/campaign-money-field"
import { ChangeBanner } from "@/integrations/meta_ads/components/change-banner"
import {
  MetaAdsLink,
  MetaAdsOutcomeTable,
  type MetaAdsOutcomeRow,
} from "@/integrations/meta_ads/components/outcome-table"
import {
  SettingLine,
  SettingRow,
  SettingRows,
} from "@/integrations/meta_ads/components/setting-rows"
import { adsManagerObjectUrl } from "@/integrations/meta_ads/lib/ads-manager-link"
import { budgetMoney } from "@/integrations/meta_ads/lib/budget-change"
import {
  adSetBidRows,
  bidProblem,
  bidsTitle,
  campaignEditRows,
  campaignNotes,
  campaignProblems,
  campaignSettingProblem,
  campaignSettingTitle,
  campaignStrategy,
  campaignSummary,
  campaignWarnings,
  changeSummary,
  editCampaigns,
  formatBid,
  formatCampaignValue,
  type CampaignChange,
  type CampaignEdit,
  type CampaignEditArgs,
  type CampaignEditResult,
  type CampaignEditRow,
  type CampaignSetting,
  type CampaignSettingKey,
} from "@/integrations/meta_ads/lib/campaign-edits"
import { BID_OPTIONS } from "@/integrations/meta_ads/lib/create-campaign"
import { formatPercentageChange, pluralize } from "@/lib/format"

type Edit = (id: string, change: CampaignChange) => void
type FieldProps = {
  campaign: CampaignEdit
  disabled: boolean
  edit: Edit
  setting: CampaignSetting
}

// Each setting sits in the Create Campaign card's row for it, in that card's order.
const ROWS: readonly { key: CampaignSettingKey; title: string }[] = [
  { key: "share_between_ad_sets", title: "Budget" },
  { key: "bid_strategy", title: "Bidding" },
  { key: "spend_limit", title: "Schedule" },
]

export function CampaignEditApproval({
  args,
  disabled,
  onFieldEdit,
  proposed,
}: {
  args: CampaignEditArgs
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
  proposed: CampaignEditArgs
}) {
  const rows = campaignEditRows(proposed, args)
  const kept = rows.filter((row) => row.included).length
  const edit: Edit = (id, change) => {
    onFieldEdit("changes", editCampaigns(rows, id, change))
  }
  return (
    <div className="grid min-w-0 gap-3">
      <ChangeBanner detail={`${String(kept)} ${pluralize(kept, "campaign")}`} />
      <SettingRows ariaLabel="Campaigns to change" defaultOpen={rows[0]?.edit.id ?? null}>
        {rows.map((row) => (
          <CampaignRow key={row.edit.id} disabled={disabled} edit={edit} row={row} />
        ))}
      </SettingRows>
    </div>
  )
}

function CampaignRow({
  disabled,
  edit,
  row,
}: {
  disabled: boolean
  edit: Edit
  row: CampaignEditRow
}) {
  const { edit: campaign, included } = row
  const problems = included ? campaignProblems(campaign) : []
  const href = adsManagerObjectUrl("campaign", campaign.accountId, campaign.id)
  const summary = !included ? "Left as it is" : (problems[0] ?? campaignSummary(campaign))
  const settings = new Map(campaign.settings.map((setting) => [setting.key, setting]))
  const name = settings.get("name")
  const grouped = ROWS.flatMap((item) => {
    const setting = settings.get(item.key)
    return setting ? [{ ...item, setting }] : []
  })
  return (
    <SettingRow
      rowKey={campaign.id}
      summary={summary}
      title={campaign.name}
      tone={problems.length > 0 ? "error" : "neutral"}
    >
      <SwitchField
        checked={included}
        disabled={disabled}
        label="Change This Campaign"
        onChange={(checked) => {
          edit(campaign.id, { included: checked })
        }}
      />
      {included ? (
        <>
          <SettingRows
            ariaLabel={`${campaign.name} settings`}
            defaultOpen={grouped[0]?.key ?? null}
          >
            {name ? (
              <NameLine campaign={campaign} disabled={disabled} edit={edit} setting={name} />
            ) : null}
            {grouped.map((item) => (
              <SettingRow
                key={item.key}
                rowKey={item.key}
                summary={changeSummary(campaign, item.setting)}
                title={item.title}
              >
                <SettingField
                  campaign={campaign}
                  disabled={disabled}
                  edit={edit}
                  setting={item.setting}
                />
              </SettingRow>
            ))}
          </SettingRows>
          {problems.map((problem) => (
            <p key={problem} className="text-destructive text-sm font-medium">
              {problem}
            </p>
          ))}
          {campaignNotes(campaign).map((note) => (
            <p key={note} className="text-foreground/75 text-sm">
              {note}
            </p>
          ))}
        </>
      ) : null}
      {href ? <MetaAdsLink href={href}>Open in Ads Manager</MetaAdsLink> : null}
    </SettingRow>
  )
}

/** The name, always shown like the Create Campaign card's, with the name now under it. */
function NameLine({ campaign, disabled, edit, setting }: FieldProps) {
  const id = useId()
  const problem = campaignSettingProblem(setting)
  const before = campaign.check?.before.name ?? null
  return (
    <SettingLine htmlFor={id} title="Name">
      <div className="grid min-w-0 gap-1 py-1">
        <Input
          aria-invalid={problem !== null}
          className="text-sm font-medium"
          disabled={disabled}
          id={id}
          onChange={(event) => {
            edit(campaign.id, { key: "name", value: event.currentTarget.value })
          }}
          value={setting.value}
        />
        {before !== null ? <Current>Current Setting: {before}</Current> : null}
        {problem ? <p className="text-destructive text-sm">{problem}</p> : null}
      </div>
    </SettingLine>
  )
}

function Current({ children }: { children: ReactNode }) {
  return (
    <p className="text-muted-foreground flex flex-wrap items-center gap-2 text-sm">{children}</p>
  )
}

function SettingField(props: FieldProps) {
  if (props.setting.key === "bid_strategy") return <BiddingField {...props} />
  if (props.setting.key === "spend_limit") return <SpendLimitField {...props} />
  return <SharingField campaign={props.campaign} />
}

/** The Create Campaign card's bid strategy cards, with a bid for each ad set when needed. */
function BiddingField({ campaign, disabled, edit, setting }: FieldProps) {
  const currency = campaign.check?.currency ?? null
  const before = campaign.check?.before.bid_strategy ?? null
  const strategy = campaignStrategy(campaign)
  const options = BID_OPTIONS.map((option) => {
    const label = option.value === before ? `${option.label} (Current Setting)` : option.label
    // A campaign can't move to a return goal here, so it stays visible but can't be picked.
    return option.value === "roas_goal" && option.value !== setting.value
      ? { ...option, label, disabledNote: "Change this in Ads Manager." }
      : { ...option, label }
  })
  return (
    <>
      <ChoiceCards
        ariaLabel="Bid strategy"
        disabled={disabled}
        onChange={(value) => {
          edit(campaign.id, { key: "bid_strategy", value })
        }}
        options={options}
        value={setting.value}
      />
      {campaign.bids.length > 0 ? (
        <section aria-label={bidsTitle(strategy)} className="grid min-w-0 gap-2">
          <p className="text-sm font-medium">{bidsTitle(strategy)}</p>
          <div className="grid min-w-0 gap-3 sm:grid-cols-2">
            {adSetBidRows(campaign).map((bid) => {
              const problem = bidProblem(bid)
              return (
                <div key={bid.id} className="grid min-w-0 gap-1">
                  <MoneyField
                    currency={currency}
                    disabled={disabled}
                    invalid={problem !== null}
                    label={bid.name}
                    onChange={(value) => {
                      edit(campaign.id, { bid: bid.id, value })
                    }}
                    value={bid.value}
                  />
                  <Current>Current Setting: {formatBid(bid.now, currency)}</Current>
                  {problem ? <p className="text-destructive text-sm">{problem}</p> : null}
                </div>
              )
            })}
          </div>
        </section>
      ) : null}
      {campaignWarnings(campaign).map((warning) => (
        <p key={warning} className="text-warning-text flex items-start gap-2 text-sm">
          <TriangleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          {warning}
        </p>
      ))}
    </>
  )
}

/** The Create Campaign card's spending limit, with the limit and spend now. */
function SpendLimitField({ campaign, disabled, edit, setting }: FieldProps) {
  const currency = campaign.check?.currency ?? null
  const before = campaign.check?.before.spend_limit ?? null
  const spent = campaign.check?.spent ?? null
  const value = setting.value === "remove" ? "" : setting.value
  const change =
    before !== null && value !== "" ? formatPercentageChange(Number(before), Number(value)) : "—"
  const problem = campaignSettingProblem(setting)
  return (
    <>
      <div className="grid min-w-0 gap-1">
        <MoneyField
          className="sm:max-w-64"
          currency={currency}
          disabled={disabled}
          invalid={problem !== null}
          label="Spending Limit (Optional)"
          onChange={(next) => {
            edit(campaign.id, { key: "spend_limit", value: next || "remove" })
          }}
          placeholder="No limit"
          value={value}
        />
        <Current>
          Current Setting: {formatCampaignValue("spend_limit", before, currency)}
          {change === "—" ? null : (
            <Badge variant={change.startsWith("+") ? "success" : "secondary"}>{change}</Badge>
          )}
        </Current>
        {problem ? <p className="text-destructive text-sm">{problem}</p> : null}
      </div>
      <p className="text-foreground/75 text-sm">
        The spending limit stops the campaign once it has spent that much in total.
        {spent !== null ? ` It has spent ${budgetMoney(spent, currency)} so far.` : ""}
      </p>
    </>
  )
}

/** The Create Campaign card's sharing switch, shown off; turning it back on isn't possible. */
function SharingField({ campaign }: { campaign: CampaignEdit }) {
  const before = campaign.check?.before.share_between_ad_sets ?? null
  return (
    <SwitchField
      checked={false}
      description={`Turning this off can't be undone. Current Setting: ${formatCampaignValue("share_between_ad_sets", before, null)}`}
      disabled
      label="Share Budget between Ad Sets"
      onChange={() => undefined}
    />
  )
}

export function CampaignEditOutcome({ result }: { result: CampaignEditResult }) {
  const rows: MetaAdsOutcomeRow[] = result.campaigns.flatMap((campaign) => {
    // Nothing was read back, so there is no value to show.
    const unread = (after: string | null) =>
      (campaign.outcome === "failed" || campaign.outcome === "unverified") && after === null
    const settings = campaign.changes.map((change) => ({
      setting: campaignSettingTitle(change.key),
      before: formatCampaignValue(change.key, change.before, result.currency),
      after: unread(change.after)
        ? "—"
        : formatCampaignValue(change.key, change.after, result.currency),
    }))
    const bids = campaign.bids.map((bid) => ({
      setting: `Bid: ${bid.name}`,
      before: formatBid(bid.before, result.currency),
      after: unread(bid.after) ? "—" : formatBid(bid.after, result.currency),
    }))
    return [...settings, ...bids].map((row, index) => ({
      name: campaign.name,
      ...row,
      outcome: campaign.outcome,
      // The campaign's message once, on its first setting.
      details: index === 0 ? (campaign.message ?? "") : "",
      errorCode: index === 0 ? campaign.errorCode : null,
    }))
  })
  return (
    <MetaAdsOutcomeTable
      columns={[
        { key: "name", kind: "text", label: "Campaign" },
        { key: "setting", kind: "text", label: "Setting" },
        { key: "before", kind: "text", label: "Before" },
        { key: "after", kind: "text", label: "After" },
      ]}
      exportFilename="meta-ads-campaign-changes.csv"
      rows={rows}
    />
  )
}
