// apps/web/src/components/tool-ui/outcome-summary.tsx

import { cn } from "@/lib/utils"

type OutcomeSummaryTone = "success" | "warning" | "danger"

export type OutcomeSummaryItem = {
  count: number
  label: string
  tone?: OutcomeSummaryTone | undefined
}

// Footer line of non-zero outcome counts.
export function OutcomeSummary({ items }: { items: readonly OutcomeSummaryItem[] }) {
  const visible = items.filter((item) => item.count > 0)
  if (visible.length === 0) return null
  return (
    <span aria-label="Outcomes" className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {visible.map((item) => (
        <span
          className={cn(
            "inline-flex items-center gap-1.5",
            item.tone === "success" && "text-success",
            item.tone === "danger" && "text-destructive"
          )}
          key={item.label}
        >
          <span
            aria-hidden="true"
            className={cn(
              "size-1.5 rounded-full",
              item.tone === "success"
                ? "bg-success"
                : item.tone === "danger"
                  ? "bg-destructive"
                  : item.tone === "warning"
                    ? "bg-warning"
                    : "bg-muted-foreground/60"
            )}
          />
          {String(item.count)} {item.label}
        </span>
      ))}
    </span>
  )
}
