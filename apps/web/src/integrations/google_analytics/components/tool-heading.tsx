// apps/web/src/integrations/google_analytics/components/tool-heading.tsx

import type { ReactNode } from "react"

import { GoogleAnalyticsLogo } from "@/integrations/google_analytics/components/logo"

export function GoogleAnalyticsToolHeading({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2 text-sm font-medium">
      <GoogleAnalyticsLogo className="size-4 shrink-0" />
      <span className="truncate">{children}</span>
    </span>
  )
}
