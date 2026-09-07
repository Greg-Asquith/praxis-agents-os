// apps/web/src/integrations/google_search_console/presenters/write-presenter.tsx

import type { ReactNode } from "react"

import { approvalDisplayError, mergeApprovalArgs } from "@/components/tool-ui/approval-args"
import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"
import { parseSettledFanOutData, type FanOutEntry } from "@/components/tool-ui/fan-out"
import { DeclinedFanOut, FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { GoogleSearchConsoleLogo } from "@/integrations/google_search_console/components/logo"
import { GoogleSearchConsoleToolHeading } from "@/integrations/google_search_console/components/tool-heading"
import type { ToolRowPresenter, ToolRowPresenterProps } from "@/integrations/contract"

type ApprovalSpec<Args> = {
  approveLabel: string
  label: string
  parseArgs: (value: unknown) => Args | null
  prompt: string
  renderSummary?: (args: Args) => ReactNode
  title: string
  validateArgs?: (value: unknown) => string | null
}

export type GoogleSearchConsoleWriteVariant<Args, Result> = {
  approval: ApprovalSpec<Args>
  deniedDescription: string
  details?: (args: Args | null) => { label: string; value: string }[]
  emptyLabel: string
  failedDescription: string
  heading: string
  malformedDescription: string
  parseResult: (value: unknown) => Result | null
  progressLabel: string
  renderOutcome: (result: Result) => ReactNode
  resultAriaLabel: string
  resultFailure: string
  unconfirmedAriaLabel: string
  unverifiedDescription: string
  waitingLabel: string
}

type WriteRenderer = (context: ToolRowPresenterProps) => ReactNode | null

export function defineGoogleSearchConsoleWriteVariant<Args, Result>(
  variant: GoogleSearchConsoleWriteVariant<Args, Result>
): WriteRenderer {
  return ({ activity, approvalDecision, defaultOpen, ui }) => {
    const args = variant.approval.parseArgs(activity.args)

    if (approvalDecision) {
      if (!args) {
        return (
          <ToolApprovalDecisionCard
            activityId={activity.id}
            approveLabel={variant.approval.approveLabel}
            args={activity.args}
            controls={approvalDecision}
            icon={<GoogleSearchConsoleLogo className="size-4" />}
            label={variant.approval.label}
            prompt="The approval details couldn't be verified, so this action can't be approved."
            title={variant.heading}
            toolName={activity.name}
            validationError="Decline this request, then ask the agent to prepare the action again."
          />
        )
      }
      const fields = ui?.arg_fields ?? []
      const currentArgs = mergeApprovalArgs(activity.args, approvalDecision.decision.edits)
      const currentParsedArgs = variant.approval.parseArgs(currentArgs)
      const validationError =
        approvalDisplayError(currentArgs) ?? variant.approval.validateArgs?.(currentArgs) ?? null
      return (
        <ToolApprovalDecisionCard
          activityId={activity.id}
          approveLabel={variant.approval.approveLabel}
          args={activity.args}
          controls={approvalDecision}
          {...(activity.derivedFromUntrusted === undefined
            ? {}
            : { derivedFromUntrusted: activity.derivedFromUntrusted })}
          fallbackFields={approvalFallbackFields(activity.args, fields)}
          fields={fields}
          icon={<GoogleSearchConsoleLogo className="size-4" />}
          label={variant.approval.label}
          prompt={variant.approval.prompt}
          {...(activity.taintSources === undefined ? {} : { taintSources: activity.taintSources })}
          title={variant.approval.title}
          toolName={activity.name}
          validationError={validationError}
        >
          {validationError || !currentParsedArgs
            ? null
            : variant.approval.renderSummary?.(currentParsedArgs)}
        </ToolApprovalDecisionCard>
      )
    }

    if (activity.status === "running" || activity.status === "awaiting_approval") {
      return (
        <FanOutSkeleton
          heading={
            <GoogleSearchConsoleToolHeading>{variant.heading}</GoogleSearchConsoleToolHeading>
          }
          label={
            activity.status === "awaiting_approval" ? variant.waitingLabel : variant.progressLabel
          }
        />
      )
    }

    if (activity.status === "denied") {
      return (
        <DeclinedFanOut
          activityId={activity.id}
          ariaLabel={variant.unconfirmedAriaLabel}
          contextLabel="Site"
          defaultOpen={defaultOpen}
          description={variant.deniedDescription}
          {...(variant.details ? { details: variant.details(args) } : {})}
          displayName="Selected Search Console site"
          externalLabel="Site URL"
          heading={
            <GoogleSearchConsoleToolHeading>{variant.heading}</GoogleSearchConsoleToolHeading>
          }
          providerKey="google_search_console"
          reason={activity.decisionReason}
        />
      )
    }

    if (activity.status === "failed" || activity.status === "unknown") {
      return writeFailure(activity.id, args, variant.failedDescription, defaultOpen, variant)
    }

    const fanOut = parseSettledFanOutData(activity.result, variant.parseResult, {
      malformed: variant.malformedDescription,
      unverified: variant.unverifiedDescription,
    })
    if (!fanOut) {
      return writeFailure(activity.id, args, variant.resultFailure, defaultOpen, variant)
    }

    return (
      <div aria-label={variant.resultAriaLabel} className="w-full min-w-0">
        <FanOutShell
          contextLabel="Site"
          defaultOpen={defaultOpen}
          {...(variant.details ? { details: variant.details(args) } : {})}
          emptyLabel={variant.emptyLabel}
          entries={fanOut.entries}
          externalLabel="Site URL"
          heading={
            <GoogleSearchConsoleToolHeading>{variant.heading}</GoogleSearchConsoleToolHeading>
          }
          renderFailed={(entry, index) => {
            const result = fanOut.data[index] ?? null
            if (entry.errorCode === "unverified_mutation" && result !== null) {
              return (
                <div className="grid gap-3">
                  <p className="text-warning-foreground bg-warning/10 rounded-md px-2.5 py-2 text-sm">
                    {entry.errorMessage ?? variant.unverifiedDescription}
                  </p>
                  {variant.renderOutcome(result)}
                </div>
              )
            }
            return (
              <p className="text-destructive text-sm">
                {entry.errorMessage ?? variant.failedDescription}
              </p>
            )
          }}
        >
          {(_entry, index) => {
            const result = fanOut.data[index] ?? null
            return result === null ? null : variant.renderOutcome(result)
          }}
        </FanOutShell>
      </div>
    )
  }
}

export function createGoogleSearchConsoleWritePresenter({
  key,
  variants,
}: {
  key: string
  variants: Record<string, WriteRenderer>
}): ToolRowPresenter {
  return {
    handlesApprovals: true,
    key,
    matches: (activity) => Object.hasOwn(variants, activity.name),
    render: (context) => variants[context.activity.name]?.(context) ?? null,
  }
}

function writeFailure<Args, Result>(
  activityId: string,
  args: Args | null,
  description: string,
  defaultOpen: boolean,
  variant: GoogleSearchConsoleWriteVariant<Args, Result>
) {
  const entry: FanOutEntry = {
    data: null,
    displayName: "Selected Search Console site",
    errorCode: null,
    errorMessage: description,
    externalId: "Selected Search Console site",
    providerKey: "google_search_console",
    renderKey: `google_search_console:failure:${activityId}`,
    status: "failed",
  }
  return (
    <div aria-label={variant.unconfirmedAriaLabel} className="w-full min-w-0">
      <FanOutShell
        contextLabel="Site"
        defaultOpen={defaultOpen}
        {...(variant.details ? { details: variant.details(args) } : {})}
        entries={[entry]}
        externalLabel="Site URL"
        heading={<GoogleSearchConsoleToolHeading>{variant.heading}</GoogleSearchConsoleToolHeading>}
      >
        {() => null}
      </FanOutShell>
    </div>
  )
}
