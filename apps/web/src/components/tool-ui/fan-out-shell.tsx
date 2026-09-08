// apps/web/src/components/tool-ui/fan-out-shell.tsx

import type { ReactNode } from "react"
import { AlertCircleIcon, CircleCheckIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { DeclinedResult } from "@/components/tool-ui/declined-result"
import type { FanOutEntry } from "@/components/tool-ui/fan-out"
import { ToolResultCard, type ToolResultDetail } from "@/components/tool-ui/result-card"

export type FanOutDetail = ToolResultDetail

const EMPTY_DETAILS: FanOutDetail[] = []

export function FanOutShell({
  children,
  contextLabel = "Connection",
  defaultOpen = false,
  details = EMPTY_DETAILS,
  entries,
  emptyLabel = "No matching items were found.",
  externalLabel = "Account",
  formatContextValue = identity,
  heading,
  renderDeclined,
  renderFailed,
}: {
  children: (entry: FanOutEntry, index: number) => ReactNode
  contextLabel?: string
  defaultOpen?: boolean
  details?: FanOutDetail[]
  entries: FanOutEntry[]
  emptyLabel?: string
  externalLabel?: string | null
  formatContextValue?: (value: string) => string
  heading?: ReactNode
  renderDeclined?: (entry: FanOutEntry, index: number) => ReactNode
  renderFailed?: (entry: FanOutEntry, index: number) => ReactNode
}) {
  const succeeded = entries.filter((entry) => entry.status === "success").length
  const allSucceeded = succeeded === entries.length
  const allFailed = succeeded === 0

  return (
    <div className="grid min-w-0 gap-3">
      {entries.length > 1 ? (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Badge variant={allSucceeded ? "success" : allFailed ? "destructive" : "warning"}>
            {allSucceeded ? <CircleCheckIcon /> : <AlertCircleIcon />}
            {allFailed
              ? "Tool failed"
              : allSucceeded
                ? "Tool ran successfully"
                : "Tool succeeded"}{" "}
            on {String(allFailed ? entries.length : succeeded)}/{String(entries.length)} connections
          </Badge>
        </div>
      ) : null}
      {entries.length === 0 ? (
        <div className="border-border bg-muted/25 rounded-lg border border-dashed px-4 py-6 text-center">
          <p className="text-muted-foreground text-sm">{emptyLabel}</p>
        </div>
      ) : null}
      {entries.map((entry, index) => (
        <FanOutCard
          contextLabel={contextLabel}
          defaultOpen={defaultOpen}
          details={details}
          entry={entry}
          externalLabel={externalLabel}
          formatContextValue={formatContextValue}
          heading={heading}
          key={entry.renderKey}
        >
          {entry.status === "success" ? (
            children(entry, index)
          ) : entry.status === "denied" && renderDeclined ? (
            renderDeclined(entry, index)
          ) : renderFailed ? (
            renderFailed(entry, index)
          ) : (
            <p className="text-destructive text-sm">
              {entry.errorMessage ?? "This connection did not return a result."}
            </p>
          )}
        </FanOutCard>
      ))}
    </div>
  )
}

export function DeclinedFanOut({
  activityId,
  ariaLabel,
  contextLabel,
  defaultOpen,
  description,
  details = EMPTY_DETAILS,
  displayName,
  externalLabel,
  formatContextValue = identity,
  heading,
  providerKey,
  reason,
}: {
  activityId: string
  ariaLabel: string
  contextLabel: string
  defaultOpen: boolean
  description: string
  details?: FanOutDetail[]
  displayName: string
  externalLabel: string | null
  formatContextValue?: (value: string) => string
  heading: ReactNode
  providerKey: string
  reason?: string | undefined
}) {
  return (
    <div aria-label={ariaLabel} className="w-full min-w-0">
      <FanOutShell
        contextLabel={contextLabel}
        defaultOpen={defaultOpen}
        details={details}
        entries={[
          {
            data: null,
            displayName,
            errorCode: null,
            errorMessage: description,
            externalId: displayName,
            providerKey,
            renderKey: `${providerKey}:denied:${activityId}`,
            status: "denied",
          },
        ]}
        externalLabel={externalLabel}
        formatContextValue={formatContextValue}
        heading={heading}
        renderDeclined={() => <DeclinedResult description={description} reason={reason} />}
      >
        {() => null}
      </FanOutShell>
    </div>
  )
}

function FanOutCard({
  children,
  contextLabel,
  defaultOpen,
  details,
  entry,
  externalLabel,
  formatContextValue,
  heading,
}: {
  children: ReactNode
  contextLabel: string
  defaultOpen: boolean
  details: FanOutDetail[]
  entry: FanOutEntry
  externalLabel: string | null
  formatContextValue: (value: string) => string
  heading?: ReactNode
}) {
  const formattedDisplayName = formatContextValue(entry.displayName)
  const visibleDetails = fanOutDetails(
    entry,
    details,
    contextLabel,
    externalLabel,
    formatContextValue
  )
  const declined = entry.status === "denied"

  return (
    <ToolResultCard
      ariaLabel={formattedDisplayName}
      defaultOpen={defaultOpen}
      details={visibleDetails}
      heading={heading ?? formattedDisplayName}
      trailing={
        <Badge
          variant={entry.status === "success" ? "success" : declined ? "secondary" : "destructive"}
        >
          {entry.status === "success" ? "Done" : declined ? "Declined" : "Failed"}
        </Badge>
      }
    >
      {children}
    </ToolResultCard>
  )
}

function fanOutDetails(
  entry: FanOutEntry,
  details: FanOutDetail[],
  contextLabel: string,
  externalLabel: string | null,
  formatContextValue: (value: string) => string
): FanOutDetail[] {
  const account =
    entry.externalId && entry.externalId !== entry.displayName
      ? formatContextValue(entry.externalId)
      : null
  return [
    { label: contextLabel, value: formatContextValue(entry.displayName) },
    ...(account && externalLabel ? [{ label: externalLabel, value: account }] : []),
    ...details,
  ]
}

function identity(value: string) {
  return value
}

export function FanOutSkeleton({
  heading,
  label,
  summary,
}: {
  heading?: ReactNode
  label: string
  summary?: string
}) {
  return (
    <section aria-busy="true" aria-label={label} className="border-border rounded-lg border p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        {heading ? (
          <div className="min-w-0">
            <div className="text-sm font-medium">{heading}</div>
            {summary ? (
              <p className="text-muted-foreground mt-0.5 truncate text-xs" title={summary}>
                {summary}
              </p>
            ) : null}
          </div>
        ) : (
          <Skeleton className="h-4 w-36" />
        )}
        <Skeleton className="h-5 w-14 rounded-full" />
      </div>
      <div className="grid gap-2">
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-12 w-4/5" />
      </div>
      <span className="sr-only">{label}</span>
    </section>
  )
}
