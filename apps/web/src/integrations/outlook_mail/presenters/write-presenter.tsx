// apps/web/src/integrations/outlook_mail/presenters/write-presenter.tsx

import { MailCheckIcon, MailQuestionIcon, MailXIcon, type LucideIcon } from "lucide-react"

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { OutlookMailLogo } from "@/integrations/outlook_mail/components/logo"
import { OutlookToolHeading } from "@/integrations/outlook_mail/components/tool-heading"
import {
  OutlookWriteOutcome,
  type OutlookOutcomeView,
} from "@/integrations/outlook_mail/components/write-outcome"
import {
  outlookWriteCopy,
  type OutlookWriteCopySpec,
} from "@/integrations/outlook_mail/lib/write-copy"
import {
  outlookWriteResult,
  type OutlookWriteResult,
} from "@/integrations/outlook_mail/lib/write-results"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
  type IntegrationWriteProvider,
  type IntegrationWriteVariant,
} from "@/integrations/write-presenter"

// Mailbox identifiers are opaque Graph IDs, so cards show only the mailbox name.
const provider: IntegrationWriteProvider = {
  contextLabel: "Mailbox",
  externalLabel: null,
  fallbackDisplayName: "Selected mailbox",
  providerKey: "outlook_mail",
  renderHeading: (heading) => <OutlookToolHeading>{heading}</OutlookToolHeading>,
  renderIcon: () => <OutlookMailLogo className="size-4" />,
}

export const MAIL_ICONS: OutlookOutcomeView["icons"] = {
  applied: MailCheckIcon,
  failed: MailXIcon,
  unverified: MailQuestionIcon,
}

export function outcomeIcons(icon: LucideIcon): OutlookOutcomeView["icons"] {
  return { applied: icon, failed: icon, unverified: icon }
}

const FAILED: OutlookWriteResult = {
  detail: null,
  message: null,
  errorCode: null,
  outcome: "failed",
  url: null,
}

export type OutlookWriteVariant<Args> = {
  copy: OutlookWriteCopySpec
  details: (args: Args | null) => FanOutDetail[]
  parseArgs: (value: unknown) => Args | null
  renderSummary?: IntegrationWriteVariant<Args, OutlookWriteResult>["approval"]["renderSummary"]
  validateArgs?: (value: unknown) => string | null
  view: (args: Args | null) => OutlookOutcomeView
}

export function defineOutlookWriteVariant<Args>(variant: OutlookWriteVariant<Args>) {
  const copy = outlookWriteCopy(variant.copy)
  const outcome = (result: OutlookWriteResult, args: Args | null, description: string | null) => (
    <OutlookWriteOutcome
      description={description}
      message={result.message}
      outcome={result.outcome}
      url={result.url}
      view={variant.view(args)}
    />
  )
  return defineIntegrationWriteVariant<Args, OutlookWriteResult>(provider, {
    ...copy,
    approval: {
      ...copy.approval,
      parseArgs: variant.parseArgs,
      ...(variant.renderSummary ? { renderSummary: variant.renderSummary } : {}),
      ...(variant.validateArgs ? { validateArgs: variant.validateArgs } : {}),
    },
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
      result.outcome === "failed" ? (result.detail ?? copy.failedDescription) : null,
  })
}

export const createOutlookWritePresenter = createIntegrationWritePresenter
