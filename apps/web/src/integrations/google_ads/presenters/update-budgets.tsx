// apps/web/src/integrations/google_ads/presenters/update-budgets.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import { UpdateBudgetsApproval } from "@/integrations/google_ads/components/update-budgets-approval"
import { UpdateBudgetsOutcome } from "@/integrations/google_ads/components/update-budgets-outcome"
import {
  budgetsApproveLabel,
  budgetsBlock,
  budgetsDetails,
  budgetsPrompt,
  parseUpdateBudgetsArgs,
  type UpdateBudgetsArgs,
} from "@/integrations/google_ads/lib/update-budgets"
import {
  parseUpdateBudgetsResult,
  type UpdateBudgetsResult,
} from "@/integrations/google_ads/lib/update-budgets-result"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const googleAdsUpdateBudgetsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_update_budgets: defineIntegrationWriteVariant<
      UpdateBudgetsArgs,
      UpdateBudgetsResult
    >(googleAdsProvider, {
      copy: { verb: "Update", object: "budgets", effect: "updated" },
      approval: {
        title: "Change Google Ads Budgets",
        approveLabel: budgetsApproveLabel,
        parseArgs: parseUpdateBudgetsArgs,
        prompt: budgetsPrompt,
        // An edit needs Google's answer, and problems follow what it last answered for.
        validateArgs: (value, checked) => budgetsBlock(parseUpdateBudgetsArgs(value), checked),
        renderInvalidDraft: true,
        renderFields: false,
        renderSummary: (value, fallback, onFieldEdit, disabled, controls) => (
          <UpdateBudgetsApproval
            args={parseUpdateBudgetsArgs(value) ?? fallback}
            checked={fallback}
            controls={controls}
            disabled={disabled}
            onFieldEdit={onFieldEdit}
          />
        ),
      },
      details: budgetsDetails,
      parseResult: parseUpdateBudgetsResult,
      settledPartial: (result) => result.rows.some((row) => row.outcome === "failed"),
      settledUnverified: (result) => result.rows.some((row) => row.outcome === "unverified"),
      settledFailure: (result) =>
        result.rows.every((row) => row.outcome === "failed")
          ? "Google Ads didn't make any of these changes."
          : null,
      renderFailure: (args, description, result) =>
        result ? (
          <div className="grid gap-3">
            <p className="text-destructive text-sm">{description}</p>
            <UpdateBudgetsOutcome result={result} />
          </div>
        ) : (
          <GoogleAdsFailureTargets
            targets={args?.changes.map((change) => change.label) ?? []}
            description={description}
          />
        ),
      renderOutcome: (result) => <UpdateBudgetsOutcome result={result} />,
      renderUnverifiedOutcome: (result) => <UpdateBudgetsOutcome result={result} />,
    }),
  },
})
