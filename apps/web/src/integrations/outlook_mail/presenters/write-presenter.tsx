// apps/web/src/integrations/outlook_mail/presenters/write-presenter.tsx

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { MessageWriteOutcome, type MessageOutcomeView } from "@/components/tool-ui/message-outcome"
import { OutlookMessageRecovery } from "@/integrations/outlook_mail/components/message-recovery"
import {
  outlookWriteResult,
  type OutlookWriteResult,
} from "@/integrations/outlook_mail/lib/write-results"
import { outlookMailProvider } from "@/integrations/outlook_mail/provider"
import { integrationWriteCopy, type IntegrationWriteCopySpec } from "@/integrations/write-copy"
import {
  defineIntegrationWriteVariant,
  type IntegrationWriteVariant,
} from "@/integrations/write-presenter"

const FAILED: OutlookWriteResult = {
  detail: null,
  message: null,
  errorCode: null,
  outcome: "failed",
  url: null,
}

export type OutlookWriteVariant<Args> = {
  copy: IntegrationWriteCopySpec
  details: (args: Args | null) => FanOutDetail[]
  parseArgs: (value: unknown) => Args | null
  prompt: string
  renderSummary?: IntegrationWriteVariant<Args, OutlookWriteResult>["approval"]["renderSummary"]
  validateArgs?: (value: unknown) => string | null
  view: (args: Args | null) => MessageOutcomeView
}

export function defineOutlookWriteVariant<Args>(variant: OutlookWriteVariant<Args>) {
  const { failedDescription } = integrationWriteCopy(outlookMailProvider, variant.copy)
  const outcome = (result: OutlookWriteResult, args: Args | null, description: string | null) => (
    <MessageWriteOutcome
      description={description}
      outcome={result.outcome}
      recovery={result.message ? <OutlookMessageRecovery message={result.message} /> : null}
      url={result.url}
      view={variant.view(args)}
    />
  )
  return defineIntegrationWriteVariant<Args, OutlookWriteResult>(outlookMailProvider, {
    approval: {
      parseArgs: variant.parseArgs,
      prompt: variant.prompt,
      ...(variant.renderSummary ? { renderSummary: variant.renderSummary } : {}),
      ...(variant.validateArgs ? { validateArgs: variant.validateArgs } : {}),
    },
    copy: variant.copy,
    details: variant.details,
    parseResult: outlookWriteResult,
    renderFailure: (args, description, result, disposition) =>
      outcome(
        { ...(result ?? FAILED), outcome: disposition === "unconfirmed" ? "unverified" : "failed" },
        args,
        description
      ),
    renderOutcome: (result, args) => outcome(result, args, null),
    renderUnverifiedOutcome: (result, args) =>
      outcome({ ...result, outcome: "unverified" }, args, null),
    settledUnverified: (result) => result.outcome === "unverified",
    settledFailure: (result) =>
      result.outcome === "failed" ? (result.detail ?? failedDescription) : null,
  })
}
