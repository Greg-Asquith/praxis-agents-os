// apps/web/src/integrations/mail-merge-presenter.tsx

import {
  countOf,
  mailMergeProblem,
  mailMergePrompt,
  parseMailMergeArgs,
  parseMailMergeResult,
  readyCount,
  type MailMergeArgs,
  type MailMergeResult,
} from "@/integrations/mail-merge"
import { MailMergeApprovalSummary } from "@/integrations/mail-merge-approval"
import { MailMergeProgressCard } from "@/integrations/mail-merge-progress"
import type { IntegrationProviderUi } from "@/integrations/provider-ui"
import { defineIntegrationWriteVariant } from "@/integrations/write-presenter"

// Gmail and Outlook share one card; only the provider's name and logo differ.
export function mailMergeWriteVariant(provider: IntegrationProviderUi) {
  return defineIntegrationWriteVariant<MailMergeArgs, MailMergeResult>(provider, {
    approval: {
      approveLabel: (args) => `Approve & Send ${countOf(readyCount(args), "Email")}`,
      parseArgs: parseMailMergeArgs,
      prompt: mailMergePrompt,
      renderFields: false,
      renderInvalidDraft: true,
      renderSummary: (value, fallback, onFieldEdit, disabled, controls) => (
        <MailMergeApprovalSummary
          args={parseMailMergeArgs(value) ?? fallback}
          controls={controls}
          disabled={disabled}
          onFieldEdit={onFieldEdit}
        />
      ),
      title: "Send Mail Merge",
      validateArgs: (value) => mailMergeProblem(parseMailMergeArgs(value), provider.name),
    },
    copy: { effect: "sent", object: "mail merge", verb: "Send" },
    parseResult: parseMailMergeResult,
    renderOutcome: (result) => (
      <MailMergeProgressCard providerName={provider.name} result={result} />
    ),
  })
}
