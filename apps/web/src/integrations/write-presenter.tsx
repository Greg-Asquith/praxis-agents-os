// apps/web/src/integrations/write-presenter.tsx

import { approvalActivityIdentity } from "@/lib/tool-activity-identity"
import type { ReactNode } from "react"
import { RefreshedWriteApproval } from "@/integrations/refreshed-write-approval"
import type { ApprovalDisplayRefresh } from "@/integrations/approval-display-query"

import { approvalDisplayError, mergeApprovalArgs } from "@/components/tool-ui/approval-args"
import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import { parseSettledFanOutData, type FanOutEntry } from "@/components/tool-ui/fan-out"
import { DeclinedFanOut, FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import type { ToolRowPresenter, ToolRowPresenterProps } from "@/integrations/contract"

export type IntegrationWriteProvider = {
  contextLabel: string
  externalLabel: string
  fallbackDisplayName: string
  formatContextValue?: (value: string) => string
  providerKey: string
  renderHeading: (heading: string) => ReactNode
  renderIcon: () => ReactNode
}

type ApprovalSpec<Args> = {
  approveLabel: string
  label: string
  parseArgs: (value: unknown) => Args | null
  prompt: string | ((args: Args) => string)
  refreshDisplay?: { fields: readonly string[]; refresh: ApprovalDisplayRefresh }
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

export type IntegrationWriteVariant<Args, Result> = {
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
  renderUnverifiedOutcome?: (result: Result) => ReactNode
  resultAriaLabel: string
  resultFailure: string
  unconfirmedAriaLabel: string
  unverifiedDescription: string
  waitingLabel: string
}

export type IntegrationWriteRenderer = (context: ToolRowPresenterProps) => ReactNode | null

export function defineIntegrationWriteVariant<Args, Result>(
  provider: IntegrationWriteProvider,
  variant: IntegrationWriteVariant<Args, Result>
): IntegrationWriteRenderer {
  return (context) => {
    const { activity, approvalDecision, defaultOpen } = context
    const args = variant.approval.parseArgs(activity.args)

    if (approvalDecision) {
      const refresh = variant.approval.refreshDisplay
      if (
        args !== null &&
        !approvalDisplayError(activity.args) &&
        refresh?.fields.some((key) => Object.hasOwn(approvalDecision.decision.edits, key))
      ) {
        return (
          <RefreshedWriteApproval
            args={mergeApprovalArgs(activity.args, approvalDecision.decision.edits)}
            locked={
              Boolean(approvalDecision.disabled) ||
              approvalDecision.submitting ||
              approvalDecision.decision.decision !== "pending"
            }
            refresh={refresh.refresh}
            toolName={activity.name}
          >
            {(value, error) => renderApproval(context, args, provider, variant, { value, error })}
          </RefreshedWriteApproval>
        )
      }
      return renderApproval(context, args, provider, variant)
    }

    if (activity.status === "running" || activity.status === "awaiting_approval") {
      return (
        <FanOutSkeleton
          heading={provider.renderHeading(variant.heading)}
          label={
            activity.status === "awaiting_approval"
              ? variant.waitingLabel
              : approvalCopy(variant.progressLabel, args)
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
        variant,
        provider
      )
    }

    if (activity.status === "failed" || activity.status === "unknown") {
      return writeFailure(
        activity.id,
        args,
        variant.failedDescription,
        defaultOpen,
        variant,
        provider
      )
    }

    const fanOut = parseSettledFanOutData(activity.result, variant.parseResult, {
      malformed: variant.malformedDescription,
      unverified: variant.unverifiedDescription,
    })
    if (!fanOut) {
      return writeFailure(activity.id, args, variant.resultFailure, defaultOpen, variant, provider)
    }

    return (
      <div aria-label={variant.resultAriaLabel} className="w-full min-w-0">
        <FanOutShell
          contextLabel={provider.contextLabel}
          defaultOpen={defaultOpen}
          {...(variant.details ? { details: variant.details(args) } : {})}
          entries={fanOut.entries}
          emptyLabel={variant.emptyLabel}
          externalLabel={provider.externalLabel}
          {...(provider.formatContextValue
            ? { formatContextValue: provider.formatContextValue }
            : {})}
          heading={provider.renderHeading(variant.heading)}
          renderFailed={(entry, index) => {
            const result = fanOut.data[index] ?? null
            if (
              entry.errorCode === "unverified_mutation" &&
              result !== null &&
              variant.renderUnverifiedOutcome
            ) {
              return (
                <div className="grid gap-3">
                  <p className="text-warning-foreground bg-warning/10 rounded-md px-2.5 py-2 text-sm">
                    {entry.errorMessage ?? variant.unverifiedDescription}
                  </p>
                  {variant.renderUnverifiedOutcome(result)}
                </div>
              )
            }
            return (
              variant.renderFailure?.(args, entry.errorMessage ?? variant.failedDescription) ?? (
                <p className="text-destructive text-sm">
                  {entry.errorMessage ?? variant.failedDescription}
                </p>
              )
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

function renderApproval<Args, Result>(
  { activity, approvalDecision, ui }: ToolRowPresenterProps,
  args: Args | null,
  provider: IntegrationWriteProvider,
  variant: IntegrationWriteVariant<Args, Result>,
  refreshed?: { value: unknown; error: string | null }
) {
  if (!approvalDecision) return null
  if (args === null) {
    return (
      <ToolApprovalDecisionCard
        activityId={approvalActivityIdentity(activity)}
        approveLabel={variant.approval.approveLabel}
        args={activity.args}
        controls={approvalDecision}
        {...(activity.derivedFromUntrusted === undefined
          ? {}
          : { derivedFromUntrusted: activity.derivedFromUntrusted })}
        {...(activity.taintSources === undefined ? {} : { taintSources: activity.taintSources })}
        icon={provider.renderIcon()}
        label={variant.approval.label}
        prompt="The approval details couldn't be verified, so this action can't be approved."
        title={variant.heading}
        toolName={activity.name}
        validationError="Decline this request, then ask the agent to prepare the action again."
      />
    )
  }
  const fields = ui?.arg_fields ?? []
  const currentArgs = refreshed
    ? refreshed.value
    : mergeApprovalArgs(activity.args, approvalDecision.decision.edits)
  const currentParsedArgs = variant.approval.parseArgs(currentArgs)
  const displayError = approvalDisplayError(currentArgs)
  const argsError = displayError ? null : (variant.approval.validateArgs?.(currentArgs) ?? null)
  const validationError =
    refreshed?.error ??
    displayError ??
    argsError ??
    (currentParsedArgs === null
      ? "The edited approval details are invalid. Correct them or decline this request."
      : null)
  const customFieldsDisabled =
    Boolean(approvalDecision.disabled) ||
    approvalDecision.submitting ||
    approvalDecision.decision.decision !== "pending"
  const editField = (key: string, value: EditedValue) => {
    if (customFieldsDisabled) return
    approvalDecision.onDecisionChange({
      decision: "pending",
      edits: { ...approvalDecision.decision.edits, [key]: value },
      message: "",
    })
  }
  const renderFields = variant.approval.renderFields !== false
  return (
    <ToolApprovalDecisionCard
      activityId={approvalActivityIdentity(activity)}
      approveLabel={variant.approval.approveLabel}
      args={activity.args}
      controls={approvalDecision}
      {...(activity.derivedFromUntrusted === undefined
        ? {}
        : { derivedFromUntrusted: activity.derivedFromUntrusted })}
      {...(activity.taintSources === undefined ? {} : { taintSources: activity.taintSources })}
      fallbackFields={
        renderFields
          ? approvalFallbackFields(
              mergeApprovalArgs(activity.args, approvalDecision.decision.edits),
              fields
            )
          : []
      }
      fields={renderFields ? fields : []}
      icon={provider.renderIcon()}
      label={variant.approval.label}
      prompt={approvalCopy(variant.approval.prompt, currentParsedArgs ?? args)}
      title={approvalCopy(variant.approval.title, currentParsedArgs ?? args)}
      toolName={activity.name}
      validationError={validationError}
    >
      {refreshed?.error || displayError || (argsError && !variant.approval.renderInvalidDraft)
        ? null
        : variant.approval.renderSummary?.(currentArgs, args, editField, customFieldsDisabled)}
    </ToolApprovalDecisionCard>
  )
}

export function createIntegrationWritePresenter({
  key,
  variants,
}: {
  key: string
  variants: Record<string, IntegrationWriteRenderer>
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

function writeDenied<Args, Result>(
  activityId: string,
  args: Args | null,
  description: string,
  reason: string | undefined,
  defaultOpen: boolean,
  variant: IntegrationWriteVariant<Args, Result>,
  provider: IntegrationWriteProvider
) {
  return (
    <DeclinedFanOut
      activityId={activityId}
      ariaLabel={variant.unconfirmedAriaLabel}
      contextLabel={provider.contextLabel}
      defaultOpen={defaultOpen}
      description={description}
      {...(variant.details ? { details: variant.details(args) } : {})}
      displayName={provider.fallbackDisplayName}
      externalLabel={provider.externalLabel}
      {...(provider.formatContextValue ? { formatContextValue: provider.formatContextValue } : {})}
      heading={provider.renderHeading(variant.heading)}
      providerKey={provider.providerKey}
      reason={reason}
    />
  )
}

function writeFailure<Args, Result>(
  activityId: string,
  args: Args | null,
  description: string,
  defaultOpen: boolean,
  variant: IntegrationWriteVariant<Args, Result>,
  provider: IntegrationWriteProvider
) {
  const entry: FanOutEntry = {
    data: null,
    displayName: provider.fallbackDisplayName,
    errorCode: null,
    errorMessage: description,
    externalId: provider.fallbackDisplayName,
    providerKey: provider.providerKey,
    renderKey: `${provider.providerKey}:failure:${activityId}`,
    status: "failed",
  }
  return (
    <div aria-label={variant.unconfirmedAriaLabel} className="w-full min-w-0">
      <FanOutShell
        contextLabel={provider.contextLabel}
        defaultOpen={defaultOpen}
        {...(variant.details ? { details: variant.details(args) } : {})}
        entries={[entry]}
        externalLabel={provider.externalLabel}
        {...(provider.formatContextValue
          ? { formatContextValue: provider.formatContextValue }
          : {})}
        heading={provider.renderHeading(variant.heading)}
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
