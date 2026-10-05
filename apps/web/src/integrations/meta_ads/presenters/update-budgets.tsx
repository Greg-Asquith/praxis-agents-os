// apps/web/src/integrations/meta_ads/presenters/update-budgets.tsx

import {
  BudgetApprovalSummary,
  BudgetOutcome,
} from "@/integrations/meta_ads/components/budget-change"
import { MetaAdsFailureTargets } from "@/integrations/meta_ads/components/outcome-table"
import {
  budgetChangeDetails,
  hasBudgetProblem,
  parseBudgetChangeArgs,
  parseBudgetChangeResult,
  type BudgetChangeArgs,
  type BudgetChangeResult,
} from "@/integrations/meta_ads/lib/budget-change"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const metaAdsUpdateBudgetsPresenter = createIntegrationWritePresenter({
  variants: {
    meta_ads_update_budgets: defineIntegrationWriteVariant<BudgetChangeArgs, BudgetChangeResult>(
      metaAdsProvider,
      {
        copy: {
          verb: "Update",
          object: "budgets",
          effect: "updated",
          check: "Check Ads Manager before taking further action.",
        },
        approval: {
          parseArgs: parseBudgetChangeArgs,
          prompt: "Review each new amount before changing how much these ads can spend.",
          // A change that breaks a budget rule or that Meta's dry run rejected can't be approved.
          validateArgs: (value) =>
            hasBudgetProblem(parseBudgetChangeArgs(value))
              ? "Decline this request, then ask the agent to change only budgets Meta allows."
              : null,
          renderInvalidDraft: true,
          renderSummary: (value, fallback) => (
            <BudgetApprovalSummary args={parseBudgetChangeArgs(value) ?? fallback} />
          ),
        },
        details: budgetChangeDetails,
        parseResult: parseBudgetChangeResult,
        settledUnverified: (result) =>
          result.budgets.some((budget) => budget.outcome === "unverified"),
        settledFailure: (result) =>
          result.budgets.every((budget) => budget.outcome === "failed")
            ? "Meta Ads didn't make any of these changes."
            : null,
        renderFailure: (args, description, result) =>
          result ? (
            <div className="grid gap-3">
              <p className="text-destructive text-sm">{description}</p>
              <BudgetOutcome result={result} />
            </div>
          ) : (
            <MetaAdsFailureTargets
              targets={args?.changes.map((change) => change.name) ?? []}
              description={description}
            />
          ),
        renderOutcome: (result) => <BudgetOutcome result={result} />,
        renderUnverifiedOutcome: (result) => <BudgetOutcome result={result} />,
      }
    ),
  },
})
