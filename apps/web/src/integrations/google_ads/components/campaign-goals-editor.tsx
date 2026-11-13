// apps/web/src/integrations/google_ads/components/campaign-goals-editor.tsx

import { PencilIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover"
import { SegmentedChoice } from "@/integrations/ads/components/controls"
import {
  ACCOUNT_GOALS,
  goalName,
  goalsText,
  hasGoal,
  toggledGoals,
  type CampaignGoal,
  type GoalOption,
} from "@/integrations/google_ads/lib/campaign-goals"

const LEVELS = [
  { value: "account", label: "Account Goals" },
  { value: "own", label: "Only These Goals" },
] as const

/** The goals a campaign bids for on one line, opening the choice between the account's and its own. */
export function CampaignGoalsEditor({
  disabled,
  label,
  onChange,
  options,
  value,
}: {
  disabled: boolean
  label: string
  onChange: (value: string | CampaignGoal[]) => void
  // Every goal the campaign can bid for, and whether it bids now.
  options: readonly GoalOption[]
  value: string | CampaignGoal[]
}) {
  const own = typeof value === "string" ? null : value
  // A requested goal the account doesn't have stays listed, so it can be cleared.
  const listed = [
    ...options,
    ...(own ?? [])
      .filter((goal) => !hasGoal(options, goal))
      .map((goal) => ({ ...goal, name: goalName(goal) })),
  ]
  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            aria-label={label}
            className="h-auto min-h-7 min-w-0 justify-between gap-2 px-2 py-1 text-left font-normal whitespace-normal"
            disabled={disabled}
            size="sm"
            type="button"
            variant="ghost"
          />
        }
      >
        <span className="wrap-anywhere">{goalsText(value)}</span>
        <PencilIcon className="text-muted-foreground shrink-0" />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[min(24rem,calc(100vw-2rem))] gap-3">
        <PopoverHeader>
          <PopoverTitle>Conversion Goals</PopoverTitle>
          <PopoverDescription className="wrap-anywhere">
            {own
              ? "This campaign bids only for the goals you select, whatever the account bids for."
              : "This campaign bids for the same goals as the account, and follows it when they change."}
          </PopoverDescription>
        </PopoverHeader>
        <SegmentedChoice
          ariaLabel="Which goals this campaign bids for"
          className="w-fit"
          compact
          disabled={disabled}
          onChange={(next) => {
            // Its own goals start as the ones that bid now, so choosing them changes nothing yet.
            onChange(
              next === "account"
                ? ACCOUNT_GOALS
                : options
                    .filter((option) => option.biddable)
                    .map(({ category, origin }) => ({ category, origin }))
            )
          }}
          options={LEVELS}
          value={own ? "own" : "account"}
        />
        {own ? (
          <ul className="grid max-h-64 gap-2 overflow-y-auto">
            {listed.map((option) => (
              <li key={`${option.category}~${option.origin}`}>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={hasGoal(own, option)}
                    disabled={disabled}
                    onCheckedChange={() => {
                      onChange(toggledGoals(own, option))
                    }}
                  />
                  <span className="wrap-anywhere">{option.name}</span>
                </label>
              </li>
            ))}
          </ul>
        ) : null}
      </PopoverContent>
    </Popover>
  )
}
