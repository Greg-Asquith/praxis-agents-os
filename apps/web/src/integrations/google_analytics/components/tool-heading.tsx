// apps/web/src/integrations/google_analytics/components/tool-heading.tsx

import type { ReactNode } from "react"

import { GoogleAnalyticsLogo } from "@/integrations/google_analytics/components/logo"

export function GoogleAnalyticsToolHeading({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2">
      <GoogleAnalyticsLogo className="size-4 shrink-0" />
      <span>{children}</span>
    </span>
  )
}
