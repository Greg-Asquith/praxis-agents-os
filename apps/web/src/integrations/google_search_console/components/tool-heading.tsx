// apps/web/src/integrations/google_search_console/components/tool-heading.tsx

import type { ReactNode } from "react"

import { GoogleSearchConsoleLogo } from "@/integrations/google_search_console/components/logo"

export function GoogleSearchConsoleToolHeading({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2 text-sm font-medium">
      <GoogleSearchConsoleLogo className="size-4 shrink-0" />
      <span className="truncate">{children}</span>
    </span>
  )
}
