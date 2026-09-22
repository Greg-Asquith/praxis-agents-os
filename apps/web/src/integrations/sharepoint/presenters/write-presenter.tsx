// apps/web/src/integrations/sharepoint/presenters/write-presenter.tsx

import { SharePointWriteOutcome } from "@/integrations/sharepoint/components/write-outcome"
import { SharePointWriteSummary } from "@/integrations/sharepoint/components/write-summary"
import {
  validateSharePointWriteArgs,
  type SharePointWriteArgs,
} from "@/integrations/sharepoint/lib/write-args"
import {
  sharePointWriteEnvelope,
  sharePointWriteRecovery,
  sharePointWriteResult,
} from "@/integrations/sharepoint/lib/write-results"
import { sharePointProvider } from "@/integrations/sharepoint/provider"
import type { IntegrationWriteCopySpec } from "@/integrations/write-copy"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export function sharePointWritePresenter({
  tool,
  copy,
  parseArgs,
  prompt,
}: {
  tool: string
  copy: IntegrationWriteCopySpec
  parseArgs: (value: unknown) => SharePointWriteArgs | null
  prompt: string
}) {
  const render = defineIntegrationWriteVariant(sharePointProvider, {
    copy: { ...copy, check: "Check the library in SharePoint before trying again." },
    approval: {
      parseArgs,
      prompt,
      validateArgs: (value) => validateSharePointWriteArgs(parseArgs(value)),
      renderSummary: (value) => {
        const args = parseArgs(value)
        return args ? <SharePointWriteSummary args={args} tool={tool} /> : null
      },
    },
    parseResult: sharePointWriteResult,
    renderOutcome: (result) => <SharePointWriteOutcome result={result} description={null} />,
    renderFailure: (_args, description, result, disposition) => (
      <SharePointWriteOutcome
        result={result}
        description={
          disposition === "unconfirmed"
            ? sharePointWriteRecovery("unverified_mutation", description)
            : sharePointWriteRecovery(result?.errorCode ?? null, description)
        }
      />
    ),
    renderUnverifiedOutcome: (result) => (
      <SharePointWriteOutcome result={result} description={null} />
    ),
    settledUnverified: (result) =>
      result.outcome === "unverified" || result.errorCode === "unverified_mutation",
    settledFailure: (result) =>
      result.outcome === "failed"
        ? sharePointWriteRecovery(
            result.errorCode,
            result.detail ?? "The change could not be completed."
          )
        : null,
  })
  return createIntegrationWritePresenter({
    variants: {
      [tool]: (context) => {
        if (context.approvalDecision || context.activity.status !== "completed")
          return render(context)
        const result = sharePointWriteEnvelope(context.activity.result)
        return result ? render({ ...context, activity: { ...context.activity, result } }) : null
      },
    },
  })
}
