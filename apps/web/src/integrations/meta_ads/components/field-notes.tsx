// apps/web/src/integrations/meta_ads/components/field-notes.tsx

import { CheckIcon, CircleAlertIcon, TriangleAlertIcon } from "lucide-react"

import type { AdCheck, RowCheck } from "@/integrations/meta_ads/lib/create-ads-checks"
import { pluralize } from "@/lib/format"
import { cn } from "@/lib/utils"

/** Errors and warnings shown under the field or section they're about. */
export function CheckMessages({ checks }: { checks: readonly AdCheck[] }) {
  if (checks.length === 0) return null
  return (
    <ul className="grid gap-1">
      {checks.map((check) => {
        const Icon = check.level === "error" ? CircleAlertIcon : TriangleAlertIcon
        return (
          <li
            key={`${check.level}:${check.message}`}
            className={cn(
              "flex items-start gap-1.5 text-xs",
              check.level === "error" ? "text-destructive" : "text-warning-foreground"
            )}
          >
            <Icon aria-hidden="true" className="mt-px size-3.5 shrink-0" />
            <span>
              <span className="sr-only">{check.level === "error" ? "Error: " : "Warning: "}</span>
              {check.message}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

/** The text's length beside Meta's recommendation, which longer text may pass but gets cut off. */
export function LengthCounter({ length, limit }: { length: number; limit: number }) {
  const over = length > limit
  return (
    <span
      className="text-muted-foreground text-xs whitespace-nowrap tabular-nums"
      title={`Meta shows about ${String(limit)} characters before cutting the text off. Longer text is allowed.`}
    >
      <span className={cn(over && "text-warning-foreground font-medium")}>
        {String(length)} {pluralize(length, "character")}
      </span>
      {" · "}
      {String(limit)} recommended
    </span>
  )
}

/** A row's check as an icon and short label, so it reads without colour; errors outrank warnings. */
export function CheckMark({ check, checks }: { check: RowCheck; checks: readonly AdCheck[] }) {
  if (check === "ready") {
    return (
      <span className="text-success flex shrink-0 items-center gap-1 text-xs">
        <CheckIcon aria-hidden="true" className="size-3.5" />
        Ready
      </span>
    )
  }
  const Icon = check === "error" ? CircleAlertIcon : TriangleAlertIcon
  const noun = check === "error" ? "Problem" : "Warning"
  const count = checks.filter((item) => item.level === check).length
  return (
    <span
      className={cn(
        "flex shrink-0 items-center gap-1 text-xs font-medium",
        check === "error" ? "text-destructive" : "text-warning-foreground"
      )}
    >
      <Icon aria-hidden="true" className="size-3.5" />
      {String(count)} {pluralize(count, noun)}
    </span>
  )
}
