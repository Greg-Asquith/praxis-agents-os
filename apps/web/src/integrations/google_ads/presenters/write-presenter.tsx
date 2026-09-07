// apps/web/src/integrations/google_ads/presenters/write-presenter.tsx

import type { ReactNode } from "react"

import { approvalDisplayError, mergeApprovalArgs } from "@/components/tool-ui/approval-args"
import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import { parseSettledFanOutData, type FanOutEntry } from "@/components/tool-ui/fan-out"
import { DeclinedFanOut, FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import type { ToolRowPresenter, ToolRowPresenterProps } from "@/integrations/contract"
import { GoogleAdsLogo } from "@/integrations/google_ads/components/logo"
import { GoogleAdsToolHeading } from "@/integrations/google_ads/components/tool-heading"
import { formatGoogleAdsAccountId } from "@/lib/format"

type ApprovalSpec<Args> = {
  approveLabel: string
  label: string
  parseArgs: (value: unknown) => Args | null
  prompt: string | ((args: Args) => string)
  renderFields?: boolean
  renderInvalidDraft?: boolean
  renderSummary?: (
    value: unknown,
    fallback: Args,
    onFieldEdit: (key: string, value: EditedValue) => void,
    disabled: boolean
  ) => ReactNode
  title: string | ((args: Args) => string)
  validateArgs?: (value: unknown) => string | null
}

export type GoogleAdsWriteVariant<Args, Result> = {
  approval: ApprovalSpec<Args>
  deniedDescription: string
  details?: (args: Args | null) => { label: string; value: string }[]
  emptyLabel: string
  failedDescription: string
  heading: string
  malformedDescription: string
  parseResult: (value: unknown) => Result | null
  progressLabel: string | ((args: Args | null) => string)
  renderFailure?: (args: Args | null, description: string) => ReactNode
  renderOutcome: (result: Result) => ReactNode
  resultAriaLabel: string
  resultFailure: string
  unconfirmedAriaLabel: string
  unverifiedDescription: string
  waitingLabel: string
}

type RenderContext = ToolRowPresenterProps

export type GoogleAdsWriteRenderer = (context: RenderContext) => ReactNode | null

export function defineGoogleAdsWriteVariant<Args, Result>(
  variant: GoogleAdsWriteVariant<Args, Result>
): GoogleAdsWriteRenderer {
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
            icon={<GoogleAdsLogo className="size-4" />}
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
      const displayError = approvalDisplayError(currentArgs)
      const argsError = variant.approval.validateArgs?.(currentArgs) ?? null
      const validationError =
        displayError ??
        argsError ??
        (currentParsedArgs === null
          ? "The edited approval details are invalid. Correct them or decline this request."
          : null)
      const editField = (key: string, value: EditedValue) => {
        if (approvalDecision.disabled || approvalDecision.submitting) return
        approvalDecision.onDecisionChange({
          decision: "pending",
          edits: { ...approvalDecision.decision.edits, [key]: value },
          message: "",
        })
      }
      const renderFields = variant.approval.renderFields !== false
      const customFieldsDisabled = approvalDecision.submitting
        ? true
        : (approvalDecision.disabled ?? false)
      return (
        <ToolApprovalDecisionCard
          activityId={activity.id}
          approveLabel={variant.approval.approveLabel}
          args={activity.args}
          controls={approvalDecision}
          fallbackFields={renderFields ? approvalFallbackFields(activity.args, fields) : []}
          fields={renderFields ? fields : []}
          icon={<GoogleAdsLogo className="size-4" />}
          label={variant.approval.label}
          prompt={approvalCopy(variant.approval.prompt, currentParsedArgs ?? args)}
          title={approvalCopy(variant.approval.title, currentParsedArgs ?? args)}
          toolName={activity.name}
          validationError={validationError}
        >
          {displayError || (argsError && !variant.approval.renderInvalidDraft)
            ? null
            : variant.approval.renderSummary?.(currentArgs, args, editField, customFieldsDisabled)}
        </ToolApprovalDecisionCard>
      )
    }

    if (activity.status === "running" || activity.status === "awaiting_approval") {
      return (
        <FanOutSkeleton
          heading={<GoogleAdsToolHeading>{variant.heading}</GoogleAdsToolHeading>}
          label={
            activity.status === "awaiting_approval"
              ? variant.waitingLabel
              : lifecycleCopy(variant.progressLabel, args)
          }
        />
      )
    }

    if (activity.status === "denied") {
      return writeDenied(
        activity.id,
        args,
        variant.deniedDescription,
        activity.decisionReason,
        defaultOpen,
        variant
      )
    }

    if (activity.status === "failed" || activity.status === "unknown") {
      return writeFailure(activity.id, args, variant.failedDescription, defaultOpen, variant)
    }

    const fanOut = parseWriteFanOut(activity.result, variant)
    if (!fanOut) {
      return writeFailure(activity.id, args, variant.resultFailure, defaultOpen, variant)
    }

    return (
      <div aria-label={variant.resultAriaLabel} className="w-full min-w-0">
        <FanOutShell
          contextLabel="Account"
          defaultOpen={defaultOpen}
          {...(variant.details ? { details: variant.details(args) } : {})}
          entries={fanOut.entries}
          emptyLabel={variant.emptyLabel}
          externalLabel="Customer ID"
          formatContextValue={formatGoogleAdsAccountId}
          heading={<GoogleAdsToolHeading>{variant.heading}</GoogleAdsToolHeading>}
          renderFailed={(entry) =>
            variant.renderFailure?.(args, entry.errorMessage ?? variant.failedDescription) ?? (
              <p className="text-destructive text-sm">
                {entry.errorMessage ?? variant.failedDescription}
              </p>
            )
          }
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

export function createGoogleAdsWritePresenter({
  key,
  variants,
}: {
  key: string
  variants: Record<string, GoogleAdsWriteRenderer>
}): ToolRowPresenter {
  return {
    handlesApprovals: true,
    key,
    matches: (activity) => Object.hasOwn(variants, activity.name),
    render: (context) => variants[context.activity.name]?.(context) ?? null,
  }
}

function approvalCopy<Args>(value: string | ((args: Args) => string), args: Args): string {
  return typeof value === "function" ? value(args) : value
}

function lifecycleCopy<Args>(
  value: string | ((args: Args | null) => string),
  args: Args | null
): string {
  return typeof value === "function" ? value(args) : value
}

function parseWriteFanOut<Args, Result>(
  value: unknown,
  variant: GoogleAdsWriteVariant<Args, Result>
): { data: (Result | null)[]; entries: FanOutEntry[] } | null {
  return parseSettledFanOutData(value, variant.parseResult, {
    malformed: variant.malformedDescription,
    unverified: variant.unverifiedDescription,
  })
}

function writeDenied<Args, Result>(
  activityId: string,
  args: Args | null,
  description: string,
  reason: string | undefined,
  defaultOpen: boolean,
  variant: GoogleAdsWriteVariant<Args, Result>
) {
  return (
    <DeclinedFanOut
      activityId={activityId}
      ariaLabel={variant.unconfirmedAriaLabel}
      contextLabel="Account"
      defaultOpen={defaultOpen}
      description={description}
      {...(variant.details ? { details: variant.details(args) } : {})}
      displayName="Selected Google Ads account"
      externalLabel="Customer ID"
      formatContextValue={formatGoogleAdsAccountId}
      heading={<GoogleAdsToolHeading>{variant.heading}</GoogleAdsToolHeading>}
      providerKey="google_ads"
      reason={reason}
    />
  )
}

function writeFailure<Args, Result>(
  activityId: string,
  args: Args | null,
  description: string,
  defaultOpen: boolean,
  variant: GoogleAdsWriteVariant<Args, Result>
) {
  const entry: FanOutEntry = {
    data: null,
    displayName: "Selected Google Ads account",
    errorCode: null,
    errorMessage: description,
    externalId: "Selected Google Ads account",
    providerKey: "google_ads",
    renderKey: `google_ads:failure:${activityId}`,
    status: "failed",
  }
  return (
    <div aria-label={variant.unconfirmedAriaLabel} className="w-full min-w-0">
      <FanOutShell
        contextLabel="Account"
        defaultOpen={defaultOpen}
        {...(variant.details ? { details: variant.details(args) } : {})}
        entries={[entry]}
        externalLabel="Customer ID"
        formatContextValue={formatGoogleAdsAccountId}
        heading={<GoogleAdsToolHeading>{variant.heading}</GoogleAdsToolHeading>}
        renderFailed={() =>
          variant.renderFailure?.(args, description) ?? (
            <p className="text-destructive text-sm">{description}</p>
          )
        }
      >
        {() => null}
      </FanOutShell>
    </div>
  )
}
