// apps/web/src/integrations/meta_ads/components/ad-set-summary.tsx

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { CreateSummary } from "@/integrations/meta_ads/components/create-summary"
import { LabelledInput } from "@/integrations/meta_ads/components/editor-fields"
import { adSetSummary, type CreateAdSetArgs } from "@/integrations/meta_ads/lib/create-ad-set"

export function CreateAdSetApproval({
  args,
  disabled,
  onFieldEdit,
}: {
  args: CreateAdSetArgs
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const ages = (key: "age_min" | "age_max", value: string) => {
    const number = Number.parseInt(value, 10)
    const { [key]: _previous, ...rest } = args.targeting
    onFieldEdit("targeting", Number.isFinite(number) ? { ...rest, [key]: number } : rest)
  }
  const ageMin = args.targeting["age_min"]
  const ageMax = args.targeting["age_max"]
  return (
    <div className="grid min-w-0 gap-3">
      <CreateSummary ariaLabel="Ad Set Summary" lines={adSetSummary(args)} />
      <p className="text-muted-foreground text-xs">
        To change the goal, places, or interests, decline and ask the agent.
      </p>
      <div className="grid min-w-0 gap-3 sm:grid-cols-3">
        {args.budget ? (
          <LabelledInput
            disabled={disabled}
            id="meta-ads-ad-set-budget"
            label={args.budget.kind === "daily" ? "Daily Budget" : "Lifetime Budget"}
            onChange={(amount) => {
              onFieldEdit("budget", { kind: args.budget?.kind ?? "daily", amount: amount.trim() })
            }}
            value={args.budget.amount}
          />
        ) : null}
        <LabelledInput
          disabled={disabled}
          id="meta-ads-ad-set-age-min"
          label="Minimum Age"
          onChange={(value) => {
            ages("age_min", value)
          }}
          value={typeof ageMin === "number" ? String(ageMin) : "18"}
        />
        <LabelledInput
          disabled={disabled}
          id="meta-ads-ad-set-age-max"
          label="Maximum Age"
          onChange={(value) => {
            ages("age_max", value)
          }}
          placeholder="65+"
          value={typeof ageMax === "number" ? String(ageMax) : ""}
        />
      </div>
    </div>
  )
}
