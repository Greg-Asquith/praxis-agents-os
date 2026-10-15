// apps/web/src/integrations/meta_ads/components/ad-set-goal.tsx

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { EntityPicker } from "@/integrations/meta_ads/components/ad-set-entity"
import { SelectField, SwitchField } from "@/integrations/meta_ads/components/campaign-controls"
import { MoneyField } from "@/integrations/meta_ads/components/campaign-money-field"
import { BID_OPTIONS, type BidStrategy } from "@/integrations/meta_ads/lib/create-campaign"
import {
  bidEdits,
  bidLabel,
  effectiveBid,
  goalEdits,
  goalsForCampaign,
  type CreateAdSetArgs,
} from "@/integrations/meta_ads/lib/create-ad-set"
import {
  ASSET_LABELS,
  CONVERSION_EVENT_LABELS,
  GOAL_DESCRIPTIONS,
  GOALS,
  type Goal,
} from "@/integrations/meta_ads/lib/goals"
import { stringValue } from "@/lib/guards"

const EVENT_OPTIONS = Object.entries(CONVERSION_EVENT_LABELS).map(([value, label]) => ({
  value,
  label,
}))
const STORE_OPTIONS = [
  { value: "google_play", label: "Google Play" },
  { value: "app_store", label: "App Store" },
]
const CUSTOM = "custom"

/** The goal, what it measures against, and how Meta bids for it. */
export function AdSetGoal({
  args,
  disabled,
  onEdit,
}: {
  args: CreateAdSetArgs
  disabled: boolean
  onEdit: (edits: Record<string, EditedValue>) => void
}) {
  const { asset, clicksBilling } = GOALS[args.goal]
  const strategy = effectiveBid(args)
  const custom = args.customConversion
  const events = custom
    ? [...EVENT_OPTIONS, { value: CUSTOM, label: `Custom Conversion: ${custom.name ?? custom.id}` }]
    : EVENT_OPTIONS
  return (
    <>
      <SelectField
        disabled={disabled}
        label="Goal"
        onChange={(goal) => {
          onEdit(goalEdits(args, goal as Goal))
        }}
        options={goalsForCampaign(args.campaign).map((goal) => ({
          value: goal,
          label: GOALS[goal].label,
        }))}
        value={args.goal}
      />
      <p className="text-foreground/75 text-sm">{GOAL_DESCRIPTIONS[args.goal]}</p>
      {asset ? (
        <EntityPicker
          currentLabel={stringValue(args.references[asset]?.["label"])}
          disabled={disabled}
          fieldKey={asset}
          label={ASSET_LABELS[asset]}
          onChoose={(value) => {
            onEdit({ [asset]: value })
          }}
        />
      ) : null}
      {asset === "pixel" ? (
        <SelectField
          disabled={disabled}
          label="What Counts as a Result"
          onChange={(value) => {
            onEdit(
              value === CUSTOM && custom
                ? { custom_conversion_id: custom.id, conversion_event: null }
                : { conversion_event: value, custom_conversion_id: null }
            )
          }}
          options={events}
          placeholder="Choose an event"
          value={custom ? CUSTOM : args.event}
        />
      ) : null}
      {asset === "app" ? (
        <SelectField
          disabled={disabled}
          label="App Store"
          onChange={(store) => {
            onEdit({ app_store: store })
          }}
          options={STORE_OPTIONS}
          placeholder="Choose a store"
          value={args.appStore}
        />
      ) : null}
      {args.campaign.bidStrategy ? (
        <p className="text-foreground/75 text-sm">
          Bidding follows the campaign: {bidLabel(args.campaign.bidStrategy)}.
        </p>
      ) : (
        <SelectField
          disabled={disabled}
          label="Bid Strategy"
          onChange={(next) => {
            onEdit(bidEdits(next as BidStrategy))
          }}
          options={BID_OPTIONS}
          value={strategy}
        />
      )}
      {strategy === "cost_per_result_goal" || strategy === "bid_cap" ? (
        <MoneyField
          className="sm:max-w-64"
          currency={args.currency}
          disabled={disabled}
          invalid={!args.bidAmount}
          label={strategy === "bid_cap" ? "Maximum Bid" : "Target Cost per Result"}
          onChange={(amount) => {
            onEdit({ bid_amount: amount || null })
          }}
          value={args.bidAmount ?? ""}
        />
      ) : null}
      {strategy === "roas_goal" ? (
        <MoneyField
          className="sm:max-w-64"
          currency={null}
          disabled={disabled}
          invalid={!args.minRoas}
          label="Minimum Return on Ad Spend"
          onChange={(ratio) => {
            onEdit({ min_roas: ratio || null })
          }}
          placeholder="For example 2.5"
          suffix="times spend"
          value={args.minRoas ?? ""}
        />
      ) : null}
      {clicksBilling ? (
        <SwitchField
          checked={args.payPerClick}
          description="Pay for each click on a link, not for each time the ad is shown."
          disabled={disabled}
          label="Pay per Click"
          onChange={(checked) => {
            onEdit({ pay_per_click: checked })
          }}
        />
      ) : null}
    </>
  )
}
