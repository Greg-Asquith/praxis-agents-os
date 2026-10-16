// apps/web/src/integrations/meta_ads/components/change-banner.tsx

import { TriangleAlertIcon } from "lucide-react"
import type { ReactNode } from "react"

/** The warning at the top of a change card, with what it changes and an optional total beside it. */
export function ChangeBanner({ aside, detail }: { aside?: ReactNode; detail: string }) {
  return (
    <div
      className="border-warning/40 bg-warning/10 flex flex-wrap items-center justify-between gap-3 rounded-lg border px-3 py-2.5"
      role="note"
    >
      <div className="grid gap-0.5">
        <p className="text-warning-text flex items-center gap-2 text-sm font-medium">
          <TriangleAlertIcon aria-hidden="true" className="size-4 shrink-0" />
          Changes take effect straight away
        </p>
        <p className="text-muted-foreground text-sm">{detail}</p>
      </div>
      {aside}
    </div>
  )
}
