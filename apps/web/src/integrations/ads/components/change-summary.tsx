// apps/web/src/integrations/ads/components/change-summary.tsx

import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export type ChangeSummaryLine = {
  // A control that edits every item in the line, such as an On/Off choice.
  action?: ReactNode
  count: number
  // Plain text after the label, such as what the count is made up of.
  detail?: string
  id: string
  label: string
  // Filters the change table to this line; the line is a button when set.
  onSelect?: () => void
  selected?: boolean
  tone?: "default" | "warning" | "danger"
}

/** One line per kind of change with its count; lines with no items are left out. */
export function ChangeSummary({ lines }: { lines: readonly ChangeSummaryLine[] }) {
  const visible = lines.filter((line) => line.count > 0)
  if (visible.length === 0) return null
  return (
    <ul aria-label="Change summary" className="divide-y overflow-hidden rounded-lg border">
      {visible.map((line) => (
        <li
          key={line.id}
          className={cn(
            "flex min-w-0 flex-wrap items-center justify-between gap-2 px-3 py-2",
            line.selected && "bg-accent/50"
          )}
        >
          <SummaryLabel line={line} />
          {line.action}
        </li>
      ))}
    </ul>
  )
}

function SummaryLabel({ line }: { line: ChangeSummaryLine }) {
  const content = (
    <>
      <span
        aria-hidden="true"
        className={cn(
          "size-1.5 shrink-0 rounded-full",
          line.tone === "warning"
            ? "bg-warning"
            : line.tone === "danger"
              ? "bg-destructive"
              : "bg-muted-foreground/60"
        )}
      />
      <span className="font-medium">{line.label}</span>
      {line.detail ? <span className="text-muted-foreground">{line.detail}</span> : null}
      <span className="text-muted-foreground tabular-nums">{String(line.count)}</span>
    </>
  )
  const className = cn(
    "flex min-w-0 items-center gap-2 text-sm",
    line.tone === "danger" && "text-destructive",
    line.tone === "warning" && "text-warning-text"
  )
  return line.onSelect ? (
    <button
      aria-pressed={line.selected ?? false}
      className={cn(className, "rounded-sm text-left hover:underline")}
      onClick={line.onSelect}
      type="button"
    >
      {content}
    </button>
  ) : (
    <span className={className}>{content}</span>
  )
}
