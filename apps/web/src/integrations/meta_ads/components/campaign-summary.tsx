// apps/web/src/integrations/meta_ads/components/campaign-summary.tsx

import { useId } from "react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Input } from "@/components/ui/input"
import { CampaignCategories } from "@/integrations/meta_ads/components/campaign-categories"
import {
  ChoiceCards,
  SelectField,
  SwitchField,
  TextField,
} from "@/integrations/meta_ads/components/campaign-controls"
import { MoneyField } from "@/integrations/meta_ads/components/campaign-money-field"
import {
  SettingLine,
  SettingRow,
  SettingRows,
} from "@/integrations/meta_ads/components/setting-rows"
import { StatusChoice } from "@/integrations/meta_ads/components/status-choice"
import { budgetMoney } from "@/integrations/meta_ads/lib/budget-change"
import {
  BID_OPTIONS,
  campaignBudgetValue,
  campaignStatusNote,
  campaignSummaries,
  roasAllowed,
  type BudgetMode,
  type CreateCampaignArgs,
} from "@/integrations/meta_ads/lib/create-campaign"
import { OBJECTIVE_KEYS, OBJECTIVES, type Objective } from "@/integrations/meta_ads/lib/objectives"

const OBJECTIVE_OPTIONS = OBJECTIVE_KEYS.map((key) => ({
  value: key,
  label: OBJECTIVES[key].label,
  description: OBJECTIVES[key].description,
}))
const SCOPE_OPTIONS = [
  { value: "campaign", label: "One Budget for the Campaign" },
  { value: "ad_set", label: "A Budget in Each Ad Set" },
]
const PERIOD_OPTIONS = [
  { value: "campaign_daily", label: "Daily" },
  { value: "campaign_lifetime", label: "Lifetime" },
]

export function CreateCampaignApproval({
  args,
  disabled,
  onEdit,
}: {
  args: CreateCampaignArgs
  disabled: boolean
  onEdit: (edits: Record<string, EditedValue>) => void
}) {
  const nameId = useId()
  const { budget, currency } = args
  const summaries = campaignSummaries(args)
  const perAdSet = budget.mode === "ad_set"
  // A return on ad spend goal only suits a sales campaign with its own budget.
  const bidReset = (objective: Objective, mode: BudgetMode): Record<string, EditedValue> =>
    args.bidStrategy === "roas_goal" && !roasAllowed(objective, mode)
      ? { bid_strategy: "highest_volume" }
      : {}
  const setBudgetMode = (mode: BudgetMode) => {
    onEdit({
      budget: campaignBudgetValue({ ...budget, mode }),
      ...bidReset(args.objective, mode),
    })
  }
  return (
    <div className="grid min-w-0 gap-3">
      <StatusChoice
        activeNote={campaignStatusNote(args)}
        disabled={disabled}
        label="Campaign Status"
        onChange={(status) => {
          onEdit({ status })
        }}
        pausedNote="Created paused. Nothing spends until you turn it on."
        value={args.status}
      />
      <SettingRows ariaLabel="Campaign Settings" defaultOpen="budget">
        <SettingLine htmlFor={nameId} title="Name">
          <Input
            className="text-sm font-medium"
            disabled={disabled}
            id={nameId}
            onChange={(event) => {
              onEdit({ name: event.currentTarget.value })
            }}
            value={args.name}
          />
        </SettingLine>
        <SettingRow rowKey="objective" summary={summaries.objective} title="Objective">
          <ChoiceCards
            ariaLabel="Objective"
            columns={2}
            disabled={disabled}
            onChange={(objective) => {
              onEdit({ objective, ...bidReset(objective as Objective, budget.mode) })
            }}
            options={OBJECTIVE_OPTIONS}
            value={args.objective}
          />
        </SettingRow>
        <SettingRow rowKey="budget" summary={summaries.budget} title="Budget">
          <ChoiceCards
            ariaLabel="Where the budget is set"
            columns={2}
            disabled={disabled}
            onChange={(scope) => {
              setBudgetMode(scope === "ad_set" ? "ad_set" : "campaign_daily")
            }}
            options={SCOPE_OPTIONS}
            value={perAdSet ? "ad_set" : "campaign"}
          />
          {perAdSet ? (
            <SwitchField
              checked={budget.shareBetweenAdSets === true}
              description="Ad sets can share up to 20% of their budgets with each other. Each needs a daily budget."
              disabled={disabled}
              label="Share Budget between Ad Sets"
              onChange={(share) => {
                onEdit({ budget: campaignBudgetValue({ ...budget, shareBetweenAdSets: share }) })
              }}
            />
          ) : (
            <>
              <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                <SelectField
                  disabled={disabled}
                  label="Budget Type"
                  onChange={(mode) => {
                    setBudgetMode(mode as BudgetMode)
                  }}
                  options={PERIOD_OPTIONS}
                  value={budget.mode}
                />
                <MoneyField
                  currency={currency}
                  disabled={disabled}
                  invalid={!budget.amount}
                  label="Amount"
                  onChange={(amount) => {
                    onEdit({ budget: campaignBudgetValue({ ...budget, amount: amount || null }) })
                  }}
                  suffix={budget.mode === "campaign_daily" ? "a day" : "in total"}
                  value={budget.amount ?? ""}
                />
              </div>
              <p className="text-foreground/75 text-sm">
                Meta spreads it across the ad sets.
                {args.minimum
                  ? ` The account minimum is ${budgetMoney(args.minimum, currency)} a day.`
                  : ""}
                {budget.mode === "campaign_daily"
                  ? " Meta may spend up to 75% more on some days, but no more than 7 times this amount in a week."
                  : ""}
              </p>
            </>
          )}
        </SettingRow>
        <SettingRow rowKey="bidding" summary={summaries.bidding} title="Bidding">
          <ChoiceCards
            ariaLabel="Bid strategy"
            disabled={disabled}
            onChange={(strategy) => {
              onEdit({ bid_strategy: strategy })
            }}
            options={BID_OPTIONS.map((option) =>
              option.value === "roas_goal" && !roasAllowed(args.objective, budget.mode)
                ? { ...option, disabledNote: "Needs a sales campaign with one campaign budget." }
                : option
            )}
            value={args.bidStrategy}
          />
        </SettingRow>
        <SettingRow rowKey="schedule" summary={summaries.schedule} title="Schedule">
          <div className="grid min-w-0 gap-3 sm:grid-cols-2">
            <TextField
              disabled={disabled}
              label="Start Date"
              onChange={(value) => {
                onEdit({ start_date: value || null })
              }}
              type="date"
              value={args.startDate ?? ""}
            />
            <TextField
              disabled={disabled}
              invalid={budget.mode === "campaign_lifetime" && !args.endDate}
              label={budget.mode === "campaign_lifetime" ? "End Date" : "End Date (Optional)"}
              onChange={(value) => {
                onEdit({ end_date: value || null })
              }}
              type="date"
              value={args.endDate ?? ""}
            />
          </div>
          <MoneyField
            className="sm:max-w-64"
            currency={currency}
            disabled={disabled}
            label="Spending Limit (Optional)"
            onChange={(amount) => {
              onEdit({ spend_limit: amount || null })
            }}
            placeholder="No limit"
            value={args.spendLimit ?? ""}
          />
          <p className="text-foreground/75 text-sm">
            Dates use the ad account's time zone{args.timezone ? ` (${args.timezone})` : ""}. The
            spending limit stops the campaign once it has spent that much in total.
          </p>
        </SettingRow>
        <SettingRow rowKey="categories" summary={summaries.categories} title="Special Ad Category">
          <CampaignCategories
            categories={args.categories}
            disabled={disabled}
            onChange={(categories) => {
              onEdit({ special_ad_categories: categories })
            }}
          />
        </SettingRow>
      </SettingRows>
    </div>
  )
}
