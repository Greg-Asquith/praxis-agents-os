// apps/web/src/integrations/write-presenter.tsx

import type { ReactNode } from "react"

import { approvalDisplayError, mergeApprovalArgs } from "@/components/tool-ui/approval-args"
import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import {
  parseSettledFanOutData,
  type FanOutEntry,
  type ParsedFanOutData,
} from "@/components/tool-ui/fan-out"
import { DeclinedFanOut, FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import type { ApprovalDisplayRefresh } from "@/integrations/approval-display-query"
import type { ToolRowPresenter, ToolRowPresenterProps } from "@/integrations/contract"
import { IntegrationToolHeading, type IntegrationProviderUi } from "@/integrations/provider-ui"
import { RefreshedWriteApproval } from "@/integrations/refreshed-write-approval"
import {
  integrationWriteCopy,
  type IntegrationWriteCopy,
  type IntegrationWriteCopySpec,
} from "@/integrations/write-copy"
import { approvalActivityIdentity } from "@/lib/tool-activity-identity"

type ApprovalSpec<Args> = {
  approveLabel?: string
  label?: string
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
  title?: string | ((args: Args) => string)
  validateArgs?: (value: unknown) => string | null
}

// Lifecycle strings default from `copy`; set one directly only when the template reads wrong.
export type IntegrationWriteVariant<Args, Result> = Partial<
  Omit<IntegrationWriteCopy, "approval" | "progressLabel">
> & {
  approval: ApprovalSpec<Args>
  copy: IntegrationWriteCopySpec
  details?: (args: Args | null) => { label: string; value: string }[]
  parseResult: (value: unknown) => Result | null
  progressLabel?: string | ((args: Args | null) => string)
  renderFailure?: (
    args: Args | null,
    description: string,
    result: Result | null,
    disposition: "failed" | "unconfirmed"
  ) => ReactNode
  renderOutcome: (result: Result, args: Args | null) => ReactNode
  renderUnverifiedOutcome?: (result: Result, args: Args | null) => ReactNode
  /** Describes a failure the provider reported inside a successful entry. */
  settledFailure?: (result: Result) => string | null
  /** Identifies ambiguous evidence even when the outer entry reports success. */
  settledUnverified?: (result: Result) => boolean
}

export type IntegrationWriteRenderer = (context: ToolRowPresenterProps) => ReactNode | null

type ResolvedVariant<Args, Result> = IntegrationWriteVariant<Args, Result> &
  Omit<IntegrationWriteCopy, "approval" | "progressLabel"> & {
    approval: ApprovalSpec<Args> & IntegrationWriteCopy["approval"]
    progressLabel: string | ((args: Args | null) => string)
  }

export function defineIntegrationWriteVariant<Args, Result>(
  provider: IntegrationProviderUi,
  spec: IntegrationWriteVariant<Args, Result>
): IntegrationWriteRenderer {
  const variant = resolveVariant(provider, spec)
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
          heading={
            <IntegrationToolHeading provider={provider}>{variant.heading}</IntegrationToolHeading>
          }
          label={
            activity.status === "awaiting_approval"
              ? variant.waitingLabel
              : approvalCopy(variant.progressLabel, args)
          }
        />
      )
    }

    if (activity.status === "denied") {
      return writeDenied(activity.id, args, activity.decisionReason, defaultOpen, variant, provider)
    }

    if (activity.status === "failed" || activity.status === "unknown") {
      return writeFailure(
        activity.id,
        args,
        activity.status === "unknown" ? variant.resultFailure : variant.failedDescription,
        defaultOpen,
        variant,
        provider,
        activity.status === "unknown" ? "unconfirmed" : "failed"
      )
    }

    return renderSettledWrite(context, args, provider, variant)
  }
}

export function createIntegrationWritePresenter({
  key,
  variants,
}: {
  key?: string
  variants: Record<string, IntegrationWriteRenderer>
}): ToolRowPresenter {
  return {
    handlesApprovals: true,
    key: key ?? Object.keys(variants).join("+"),
    matches: (activity) => Object.hasOwn(variants, activity.name),
    render: (context) => variants[context.activity.name]?.(context) ?? null,
  }
}

function resolveVariant<Args, Result>(
  provider: IntegrationProviderUi,
  spec: IntegrationWriteVariant<Args, Result>
): ResolvedVariant<Args, Result> {
  const copy = integrationWriteCopy(provider, spec.copy)
  const { approval, ...rest } = spec
  return {
    ...copy,
    ...definedEntries(rest),
    approval: { ...copy.approval, ...definedEntries(approval) },
    progressLabel: spec.progressLabel ?? copy.progressLabel,
  } as ResolvedVariant<Args, Result>
}

function definedEntries<T extends object>(value: T): Partial<T> {
  return Object.fromEntries(
    Object.entries(value).filter(([, item]) => item !== undefined)
  ) as Partial<T>
}

function renderSettledWrite<Args, Result>(
  { activity, defaultOpen }: ToolRowPresenterProps,
  args: Args | null,
  provider: IntegrationProviderUi,
  variant: ResolvedVariant<Args, Result>
) {
  const fanOut = parseSettledFanOutData(activity.result, variant.parseResult, {
    malformed: variant.malformedDescription,
    unverified: variant.unverifiedDescription,
  })
  if (!fanOut) {
    return writeFailure(
      activity.id,
      args,
      variant.resultFailure,
      defaultOpen,
      variant,
      provider,
      "unconfirmed"
    )
  }
  const entries = settleEntries(fanOut, variant)

  return (
    <div aria-label={variant.resultAriaLabel} className="w-full min-w-0">
      <FanOutShell
        contextLabel={provider.contextLabel}
        defaultOpen={defaultOpen}
        {...(variant.details ? { details: variant.details(args) } : {})}
        entries={entries}
        emptyLabel={variant.emptyLabel}
        externalLabel={provider.externalLabel}
        {...(provider.formatContextValue
          ? { formatContextValue: provider.formatContextValue }
          : {})}
        heading={
          <IntegrationToolHeading provider={provider}>{variant.heading}</IntegrationToolHeading>
        }
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
                {variant.renderUnverifiedOutcome(result, args)}
              </div>
            )
          }
          return (
            variant.renderFailure?.(
              args,
              entry.errorMessage ?? variant.failedDescription,
              result,
              entry.status === "unconfirmed" ? "unconfirmed" : "failed"
            ) ?? (
              <p className="text-destructive text-sm">
                {entry.errorMessage ?? variant.failedDescription}
              </p>
            )
          )
        }}
      >
        {(_entry, index) => {
          const result = fanOut.data[index] ?? null
          return result === null ? null : variant.renderOutcome(result, args)
        }}
      </FanOutShell>
    </div>
  )
}

function renderApproval<Args, Result>(
  { activity, approvalDecision, ui }: ToolRowPresenterProps,
  args: Args | null,
  provider: IntegrationProviderUi,
  variant: ResolvedVariant<Args, Result>,
  refreshed?: { value: unknown; error: string | null }
) {
  if (!approvalDecision) return null
  const provenance = {
    ...(activity.derivedFromUntrusted === undefined
      ? {}
      : { derivedFromUntrusted: activity.derivedFromUntrusted }),
    ...(activity.taintSources === undefined ? {} : { taintSources: activity.taintSources }),
  }
  const icon = <provider.Logo aria-hidden="true" className="size-4" />
  if (args === null) {
    return (
      <ToolApprovalDecisionCard
        activityId={approvalActivityIdentity(activity)}
        approveLabel={variant.approval.approveLabel}
        args={activity.args}
        controls={approvalDecision}
        {...provenance}
        icon={icon}
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
      {...provenance}
      fallbackFields={
        renderFields
          ? approvalFallbackFields(
              mergeApprovalArgs(activity.args, approvalDecision.decision.edits),
              fields
            )
          : []
      }
      fields={renderFields ? fields : []}
      icon={icon}
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

function approvalCopy<Args>(value: string | ((args: Args) => string), args: Args): string {
  return typeof value === "function" ? value(args) : value
}

// Parsed provider evidence can override a successful outer status.
function settleEntries<Args, Result>(
  fanOut: ParsedFanOutData<Result>,
  variant: ResolvedVariant<Args, Result>
): FanOutEntry[] {
  return fanOut.entries.map((entry, index) => {
    if (entry.errorCode === "malformed_result" || entry.errorCode === "unverified_mutation") {
      return { ...entry, status: "unconfirmed" }
    }
    const result = fanOut.data[index] ?? null
    if (entry.status !== "success" || result === null) return entry
    if (variant.settledUnverified?.(result)) {
      return {
        ...entry,
        status: "unconfirmed",
        errorCode: "unverified_mutation",
        errorMessage: variant.unverifiedDescription,
      }
    }
    const description = variant.settledFailure?.(result) ?? null
    return description === null
      ? entry
      : { ...entry, errorCode: null, errorMessage: description, status: "failed" }
  })
}

function writeDenied<Args, Result>(
  activityId: string,
  args: Args | null,
  reason: string | undefined,
  defaultOpen: boolean,
  variant: ResolvedVariant<Args, Result>,
  provider: IntegrationProviderUi
) {
  return (
    <DeclinedFanOut
      activityId={activityId}
      ariaLabel={variant.unconfirmedAriaLabel}
      contextLabel={provider.contextLabel}
      defaultOpen={defaultOpen}
      description={variant.deniedDescription}
      {...(variant.details ? { details: variant.details(args) } : {})}
      displayName={provider.fallbackDisplayName}
      externalLabel={provider.externalLabel}
      {...(provider.formatContextValue ? { formatContextValue: provider.formatContextValue } : {})}
      heading={
        <IntegrationToolHeading provider={provider}>{variant.heading}</IntegrationToolHeading>
      }
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
  variant: ResolvedVariant<Args, Result>,
  provider: IntegrationProviderUi,
  disposition: "failed" | "unconfirmed"
) {
  const entry: FanOutEntry = {
    data: null,
    displayName: provider.fallbackDisplayName,
    errorCode: null,
    errorMessage: description,
    externalId: provider.fallbackDisplayName,
    providerKey: provider.providerKey,
    renderKey: `${provider.providerKey}:failure:${activityId}`,
    status: disposition,
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
        heading={
          <IntegrationToolHeading provider={provider}>{variant.heading}</IntegrationToolHeading>
        }
        renderFailed={() =>
          variant.renderFailure?.(args, description, null, disposition) ?? (
            <p className="text-destructive text-sm">{description}</p>
          )
        }
      >
        {() => null}
      </FanOutShell>
    </div>
  )
}
