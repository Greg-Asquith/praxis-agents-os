// apps/web/src/integrations/google_ads/presenters/write-presenter.tsx

import type { ReactNode } from "react"

import { mergeApprovalArgs } from "@/components/tool-ui/approval-args"
import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"
import { fanOutEntries, type FanOutEntry } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import type { ToolRowPresenter } from "@/integrations/contract"
import { GoogleAdsLogo } from "@/integrations/google_ads/components/logo"
import { GoogleAdsToolHeading } from "@/integrations/google_ads/components/tool-heading"
import { formatGoogleAdsAccountId } from "@/lib/format"

type ApprovalSpec<Args> = {
  approveLabel: string
  label: string
  parseArgs: (value: unknown) => Args | null
  prompt: string | ((args: Args) => string)
  renderSummary?: (value: unknown, fallback: Args) => ReactNode
  title: string | ((args: Args) => string)
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

type AnyWriteVariant = GoogleAdsWriteVariant<unknown, unknown>

export function defineGoogleAdsWriteVariant<Args, Result>(
  variant: GoogleAdsWriteVariant<Args, Result>
): GoogleAdsWriteVariant<Args, Result> {
  return variant
}

export function createGoogleAdsWritePresenter({
  key,
  variants,
}: {
  key: string
  variants: Record<string, object>
}): ToolRowPresenter {
  return {
    handlesApprovals: true,
    key,
    matches: (activity) => Object.hasOwn(variants, activity.name),
    render: ({ activity, approvalDecision, defaultOpen, ui }) => {
      const configuredVariant = variants[activity.name]
      if (!configuredVariant) {
        return null
      }
      const variant = configuredVariant as unknown as AnyWriteVariant
      const args = variant.approval.parseArgs(activity.args)

      if (approvalDecision) {
        if (!args) {
          return null
        }
        const fields = ui?.arg_fields ?? []
        const currentArgs = mergeApprovalArgs(activity.args, approvalDecision.decision.edits)
        const currentParsedArgs = variant.approval.parseArgs(currentArgs) ?? args
        return (
          <ToolApprovalDecisionCard
            activityId={activity.id}
            approveLabel={variant.approval.approveLabel}
            args={activity.args}
            controls={approvalDecision}
            fallbackFields={approvalFallbackFields(activity.args, fields)}
            fields={fields}
            icon={<GoogleAdsLogo className="size-4" />}
            label={variant.approval.label}
            prompt={approvalCopy(variant.approval.prompt, currentParsedArgs)}
            title={approvalCopy(variant.approval.title, currentParsedArgs)}
            toolName={activity.name}
          >
            {variant.approval.renderSummary?.(currentArgs, args)}
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

      if (
        activity.status === "denied" ||
        activity.status === "failed" ||
        activity.status === "unknown"
      ) {
        return writeFailure(
          activity.id,
          args,
          activity.status === "denied" ? variant.deniedDescription : variant.failedDescription,
          defaultOpen,
          variant
        )
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
              const result = fanOut.data[index]
              return result === null ? null : variant.renderOutcome(result)
            }}
          </FanOutShell>
        </div>
      )
    },
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

function parseWriteFanOut(
  value: unknown,
  variant: AnyWriteVariant
): { data: unknown[]; entries: FanOutEntry[] } | null {
  const parsedEntries = fanOutEntries(value)
  if (!parsedEntries) {
    return null
  }
  const data: unknown[] = []
  const entries = parsedEntries.map((entry) => {
    if (entry.status !== "success") {
      data.push(null)
      return entry.errorCode === "unverified_mutation"
        ? { ...entry, errorMessage: variant.unverifiedDescription }
        : entry
    }
    const result = variant.parseResult(entry.data)
    data.push(result)
    return result === null
      ? {
          ...entry,
          errorCode: "malformed_result",
          errorMessage: variant.malformedDescription,
          status: "failed",
        }
      : entry
  })
  return { data, entries }
}

function writeFailure<Args>(
  activityId: string,
  args: Args | null,
  description: string,
  defaultOpen: boolean,
  variant: GoogleAdsWriteVariant<Args, unknown>
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
