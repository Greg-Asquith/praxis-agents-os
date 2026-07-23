// apps/web/src/integrations/google_ads/tool-heading.tsx

import { GoogleAdsLogo } from "@/integrations/google_ads/logo"

export function GoogleAdsToolHeading({ children }: { children: string }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <GoogleAdsLogo className="size-4 shrink-0" />
      <span className="truncate">{children}</span>
    </span>
  )
}
