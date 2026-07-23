// apps/web/src/components/tool-ui/fan-out-shell.tsx

import type { ReactNode } from "react"
import { AlertCircleIcon, CircleCheckIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import type { FanOutEntry } from "@/components/tool-ui/fan-out"
import { ToolResultCard, type ToolResultDetail } from "@/components/tool-ui/result-card"

export type FanOutDetail = ToolResultDetail

const EMPTY_DETAILS: FanOutDetail[] = []

export function FanOutShell({
  children,
  contextLabel = "Connection",
  details = EMPTY_DETAILS,
  entries,
  emptyLabel = "No matching items were found.",
  externalLabel = "Account",
  heading,
  renderFailed,
}: {
  children: (entry: FanOutEntry, index: number) => ReactNode
  contextLabel?: string
  details?: FanOutDetail[]
  entries: FanOutEntry[]
  emptyLabel?: string
  externalLabel?: string
  heading?: ReactNode
  renderFailed?: (entry: FanOutEntry, index: number) => ReactNode
}) {
  const succeeded = entries.filter((entry) => entry.status === "success").length
  const failed = entries.length - succeeded

  return (
    <div className="grid min-w-0 gap-3">
      {entries.length > 1 ? (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Badge variant="success">
            <CircleCheckIcon /> {String(succeeded)} Succeeded
          </Badge>
          {failed > 0 ? (
            <Badge variant="destructive">
              <AlertCircleIcon /> {String(failed)} Failed
            </Badge>
          ) : null}
        </div>
      ) : null}
      {entries.length === 0 ? (
        <div className="border-border/70 bg-muted/25 rounded-lg border border-dashed px-4 py-6 text-center">
          <p className="text-muted-foreground text-sm">{emptyLabel}</p>
        </div>
      ) : null}
      {entries.map((entry, index) => (
        <FanOutCard
          contextLabel={contextLabel}
          details={details}
          entry={entry}
          externalLabel={externalLabel}
          heading={heading}
          key={`${entry.connectionId}:${entry.externalId}`}
        >
          {entry.status === "success" ? (
            children(entry, index)
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

function FanOutCard({
  children,
  contextLabel,
  details,
  entry,
  externalLabel,
  heading,
}: {
  children: ReactNode
  contextLabel: string
  details: FanOutDetail[]
  entry: FanOutEntry
  externalLabel: string
  heading?: ReactNode
}) {
  const visibleDetails = fanOutDetails(entry, details, contextLabel, externalLabel)

  return (
    <ToolResultCard
      ariaLabel={entry.displayName}
      details={visibleDetails}
      heading={heading ?? entry.displayName}
      trailing={
        <Badge variant={entry.status === "success" ? "success" : "destructive"}>
          {entry.status === "success" ? "Done" : "Failed"}
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
  externalLabel: string
): FanOutDetail[] {
  const account =
    entry.externalId && entry.externalId !== entry.displayName ? entry.externalId : null
  return [
    { label: contextLabel, value: entry.displayName },
    ...(account ? [{ label: externalLabel, value: account }] : []),
    ...details,
  ]
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
    <section aria-busy="true" aria-label={label} className="border-border/70 rounded-lg border p-3">
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
