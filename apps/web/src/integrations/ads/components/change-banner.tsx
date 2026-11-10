// apps/web/src/integrations/ads/components/change-banner.tsx

import { Trash2Icon, TriangleAlertIcon } from "lucide-react"
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

/** The warning at the top of a change card; the danger tone is for changes that can't be undone. */
export function ChangeBanner({
  aside,
  detail,
  title = "Changes take effect straight away",
  tone = "warning",
}: {
  aside?: ReactNode
  detail: ReactNode
  title?: string
  tone?: "warning" | "danger"
}) {
  const Icon = tone === "danger" ? Trash2Icon : TriangleAlertIcon
  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 rounded-lg border px-3 py-2.5",
        tone === "danger"
          ? "border-destructive/40 bg-destructive/5"
          : "border-warning/40 bg-warning/10"
      )}
      role="note"
    >
      <div className="grid gap-0.5">
        <p
          className={cn(
            "flex items-center gap-2 text-sm font-medium",
            tone === "danger" ? "text-destructive" : "text-warning-text"
          )}
        >
          <Icon aria-hidden="true" className="size-4 shrink-0" />
          {title}
        </p>
        <div className="text-muted-foreground text-sm">{detail}</div>
      </div>
      {aside}
    </div>
  )
}
