// apps/web/src/integrations/meta_ads/components/ad-set-summary.tsx

import { useId } from "react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Input } from "@/components/ui/input"
import { AdSetGoal } from "@/integrations/meta_ads/components/ad-set-goal"
import { AdSetPlacements } from "@/integrations/meta_ads/components/ad-set-placements"
import {
  AdSetInterests,
  AdSetLocations,
  AdSetPeople,
} from "@/integrations/meta_ads/components/ad-set-targeting"
import { SelectField, TextField } from "@/integrations/meta_ads/components/campaign-controls"
import { MoneyField } from "@/integrations/meta_ads/components/campaign-money-field"
import {
  SettingLine,
  SettingRow,
  SettingRows,
} from "@/integrations/meta_ads/components/setting-rows"
import { StatusChoice } from "@/integrations/meta_ads/components/status-choice"
import { budgetMoney } from "@/integrations/meta_ads/lib/budget-change"
import {
  adSetStatusNote,
  adSetSummaries,
  type CreateAdSetArgs,
} from "@/integrations/meta_ads/lib/create-ad-set"
import { OBJECTIVES } from "@/integrations/meta_ads/lib/objectives"

const KIND_OPTIONS = [
  { value: "daily", label: "Daily" },
  { value: "lifetime", label: "Lifetime" },
]

export function CreateAdSetApproval({
  args,
  disabled,
  onEdit,
}: {
  args: CreateAdSetArgs
  disabled: boolean
  onEdit: (edits: Record<string, EditedValue>) => void
}) {
  const nameId = useId()
  const summaries = adSetSummaries(args)
  const { campaign, currency, budget } = args
  const kind = budget?.kind ?? "daily"
  const onTargeting = (targeting: Record<string, unknown>) => {
    onEdit({ targeting })
  }
  const euMissing = args.euApplies && summaries.eu.startsWith("Needs")
  return (
    <div className="grid min-w-0 gap-3">
      <StatusChoice
        activeNote={adSetStatusNote(args)}
        disabled={disabled}
        label="Ad Set Status"
        onChange={(status) => {
          onEdit({ status })
        }}
        pausedNote="Created paused. Nothing spends until you turn it on."
        value={args.status}
      />
      <SettingRows ariaLabel="Ad Set Settings" defaultOpen="goal">
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
        <SettingLine title="Campaign">
          <p className="truncate text-sm">
            {campaign.name}
            {campaign.objective ? ` · ${OBJECTIVES[campaign.objective].label}` : ""}
          </p>
        </SettingLine>
        <SettingRow rowKey="goal" summary={summaries.goal} title="Goal">
          <AdSetGoal args={args} disabled={disabled} onEdit={onEdit} />
        </SettingRow>
        <SettingRow rowKey="budget" summary={summaries.budget} title="Budget and Schedule">
          {campaign.budget ? (
            <p className="text-foreground/75 text-sm">
              The campaign holds the budget
              {campaign.budget.amount
                ? `: ${budgetMoney(campaign.budget.amount, currency)}${campaign.budget.period === "lifetime" ? " in total" : " a day"}`
                : ""}
              .
            </p>
          ) : (
            <div className="grid min-w-0 gap-3 sm:grid-cols-2">
              <SelectField
                disabled={disabled || campaign.shareBetweenAdSets}
                label="Budget Type"
                onChange={(next) => {
                  onEdit({ budget: { kind: next, amount: budget?.amount ?? "" } })
                }}
                options={KIND_OPTIONS}
                value={kind}
              />
              <MoneyField
                currency={currency}
                disabled={disabled}
                invalid={!budget?.amount}
                label="Amount"
                onChange={(amount) => {
                  onEdit({ budget: { kind, amount } })
                }}
                suffix={kind === "daily" ? "a day" : "in total"}
                value={budget?.amount ?? ""}
              />
            </div>
          )}
          {args.minimum && !campaign.budget ? (
            <p className="text-foreground/75 text-sm">
              Meta's minimum for this goal is about {budgetMoney(args.minimum, currency)} a day.
            </p>
          ) : null}
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
              invalid={kind === "lifetime" && !campaign.budget && !args.endDate}
              label={kind === "lifetime" && !campaign.budget ? "End Date" : "End Date (Optional)"}
              onChange={(value) => {
                onEdit({ end_date: value || null })
              }}
              type="date"
              value={args.endDate ?? ""}
            />
          </div>
          <p className="text-foreground/75 text-sm">
            Dates use the ad account's time zone{args.timezone ? ` (${args.timezone})` : ""}.
          </p>
        </SettingRow>
        <SettingRow rowKey="locations" summary={summaries.locations} title="Locations">
          <AdSetLocations args={args} disabled={disabled} onTargeting={onTargeting} />
        </SettingRow>
        <SettingRow rowKey="people" summary={summaries.people} title="Age and Gender">
          <AdSetPeople args={args} disabled={disabled} onTargeting={onTargeting} />
        </SettingRow>
        <SettingRow rowKey="interests" summary={summaries.interests} title="Interests">
          <AdSetInterests args={args} disabled={disabled} onTargeting={onTargeting} />
        </SettingRow>
        <SettingRow rowKey="placements" summary={summaries.placements} title="Placements">
          <AdSetPlacements
            disabled={disabled}
            onChange={(placements) => {
              onEdit({ placements })
            }}
            placements={args.placements}
          />
        </SettingRow>
        {args.euApplies ? (
          <SettingRow
            rowKey="eu"
            summary={summaries.eu}
            title="EU Transparency"
            tone={euMissing ? "warning" : "neutral"}
          >
            <p className="text-foreground/75 text-sm">
              Meta shows these names publicly in its ad library.
            </p>
            <div className="grid min-w-0 gap-3 sm:grid-cols-2">
              <TextField
                disabled={disabled}
                label="Who Pays for the Ads"
                onChange={(value) => {
                  onEdit({ eu_payer: value.trim() ? value : null })
                }}
                placeholder={args.defaultPayer ?? ""}
                value={args.euPayer ?? ""}
              />
              <TextField
                disabled={disabled}
                label="Who the Ads Benefit"
                onChange={(value) => {
                  onEdit({ eu_beneficiary: value.trim() ? value : null })
                }}
                placeholder={args.defaultBeneficiary ?? ""}
                value={args.euBeneficiary ?? ""}
              />
            </div>
          </SettingRow>
        ) : null}
      </SettingRows>
    </div>
  )
}
