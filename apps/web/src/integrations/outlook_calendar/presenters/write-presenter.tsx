// apps/web/src/integrations/outlook_calendar/presenters/write-presenter.tsx

import { CalendarCheckIcon, CalendarClockIcon, CalendarX2Icon } from "lucide-react"

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import {
  MessageWriteOutcome,
  type MessageOutcome,
  type MessageOutcomeView,
} from "@/components/tool-ui/message-outcome"
import {
  outlookCalendarWriteResult,
  type OutlookCalendarWriteResult,
} from "@/integrations/outlook_calendar/lib/write-results"
import { outlookCalendarProvider } from "@/integrations/outlook_calendar/provider"
import { integrationWriteCopy, type IntegrationWriteCopySpec } from "@/integrations/write-copy"
import {
  defineIntegrationWriteVariant,
  type IntegrationWriteVariant,
} from "@/integrations/write-presenter"

const CALENDAR_OUTCOME_ICONS = {
  applied: CalendarCheckIcon,
  failed: CalendarX2Icon,
  unverified: CalendarClockIcon,
}

const FAILED: OutlookCalendarWriteResult = {
  action: "",
  detail: null,
  event: null,
  joinUrl: null,
  outcome: "failed",
  url: null,
}

type CalendarOutcomeView = Omit<MessageOutcomeView, "body" | "icons" | "linkLabel">

export type OutlookCalendarWriteVariant<Args> = {
  approveLabel?: string
  copy: IntegrationWriteCopySpec
  details: (args: Args | null) => FanOutDetail[]
  parseArgs: (value: unknown) => Args | null
  prompt: string
  renderSummary?: IntegrationWriteVariant<
    Args,
    OutlookCalendarWriteResult
  >["approval"]["renderSummary"]
  validateArgs?: (value: unknown) => string | null
  visibleFields?: IntegrationWriteVariant<
    Args,
    OutlookCalendarWriteResult
  >["approval"]["visibleFields"]
  view: (args: Args | null, result: OutlookCalendarWriteResult) => CalendarOutcomeView
}

export function defineOutlookCalendarWriteVariant<Args>(
  variant: OutlookCalendarWriteVariant<Args>
) {
  const { failedDescription } = integrationWriteCopy(outlookCalendarProvider, variant.copy)
  const outcome = (
    result: OutlookCalendarWriteResult,
    args: Args | null,
    description: string | null,
    state: MessageOutcome = result.outcome
  ) => (
    <MessageWriteOutcome
      description={description}
      outcome={state}
      url={result.url}
      view={{
        ...variant.view(args, result),
        body: null,
        icons: CALENDAR_OUTCOME_ICONS,
        linkLabel: () => "Open in Outlook",
      }}
    />
  )
  return defineIntegrationWriteVariant<Args, OutlookCalendarWriteResult>(outlookCalendarProvider, {
    approval: {
      ...(variant.approveLabel ? { approveLabel: variant.approveLabel } : {}),
      parseArgs: variant.parseArgs,
      prompt: variant.prompt,
      // The summary holds editable controls, so it stays while another field is invalid.
      ...(variant.renderSummary
        ? { renderInvalidDraft: true, renderSummary: variant.renderSummary }
        : {}),
      ...(variant.validateArgs ? { validateArgs: variant.validateArgs } : {}),
      ...(variant.visibleFields ? { visibleFields: variant.visibleFields } : {}),
    },
    copy: variant.copy,
    details: variant.details,
    parseResult: outlookCalendarWriteResult,
    renderFailure: (args, description, result, disposition) =>
      outcome(
        result ?? FAILED,
        args,
        description,
        disposition === "unconfirmed" ? "unverified" : "failed"
      ),
    renderOutcome: (result, args) => outcome(result, args, null),
    renderUnverifiedOutcome: (result, args) => outcome(result, args, null, "unverified"),
    settledUnverified: (result) => result.outcome === "unverified",
    settledFailure: (result) =>
      result.outcome === "failed" ? (result.detail ?? failedDescription) : null,
  })
}
