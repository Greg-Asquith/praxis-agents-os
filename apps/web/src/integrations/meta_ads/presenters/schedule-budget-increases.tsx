// apps/web/src/integrations/meta_ads/presenters/schedule-budget-increases.tsx

import {
  BudgetScheduleApproval,
  BudgetScheduleOutcome,
} from "@/integrations/meta_ads/components/budget-schedule"
import { MetaAdsFailureTargets } from "@/integrations/meta_ads/components/outcome-table"
import {
  budgetScheduleDetails,
  budgetScheduleProblem,
  parseBudgetScheduleArgs,
  parseBudgetScheduleResult,
  type BudgetScheduleArgs,
  type BudgetScheduleResult,
} from "@/integrations/meta_ads/lib/budget-schedule"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const metaAdsScheduleBudgetIncreasesPresenter = createIntegrationWritePresenter({
  variants: {
    meta_ads_schedule_budget_increases: defineIntegrationWriteVariant<
      BudgetScheduleArgs,
      BudgetScheduleResult
    >(metaAdsProvider, {
      copy: {
        verb: "Add",
        object: "budget increases",
        effect: "added",
        check: "Check the budget schedule in Ads Manager before taking further action.",
      },
      approval: {
        parseArgs: parseBudgetScheduleArgs,
        prompt: "Review each period before raising how much these ads can spend.",
        // A broken period or a target Meta won't schedule can't be approved.
        validateArgs: (value) => budgetScheduleProblem(parseBudgetScheduleArgs(value)),
        renderInvalidDraft: true,
        renderSummary: (value, fallback, onFieldEdit, disabled) => (
          <BudgetScheduleApproval
            args={parseBudgetScheduleArgs(value) ?? fallback}
            disabled={disabled}
            onFieldEdit={onFieldEdit}
            proposed={fallback}
          />
        ),
      },
      details: budgetScheduleDetails,
      parseResult: parseBudgetScheduleResult,
      settledPartial: (result) => result.periods.some((period) => period.outcome === "failed"),
      settledUnverified: (result) =>
        result.periods.some((period) => period.outcome === "unverified"),
      settledFailure: (result) =>
        result.periods.every((period) => period.outcome === "failed")
          ? "Meta Ads didn't add any of these periods."
          : null,
      renderFailure: (args, description, result) =>
        result ? (
          <div className="grid gap-3">
            <p className="text-destructive text-sm">{description}</p>
            <BudgetScheduleOutcome result={result} />
          </div>
        ) : (
          <MetaAdsFailureTargets targets={args ? [args.name] : []} description={description} />
        ),
      renderOutcome: (result) => <BudgetScheduleOutcome result={result} />,
      renderUnverifiedOutcome: (result) => <BudgetScheduleOutcome result={result} />,
    }),
  },
})
