// apps/web/src/integrations/google_analytics/components/logo.tsx

import type { SVGProps } from "react"

export function GoogleAnalyticsLogo(props: SVGProps<SVGSVGElement>) {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 32 32" {...props}>
      <rect x="4" y="20" width="7" height="8" rx="3.5" fill="#f9ab00" />
      <rect x="13" y="11" width="7" height="17" rx="3.5" fill="#e37400" />
      <rect x="22" y="3" width="7" height="25" rx="3.5" fill="#e37400" />
    </svg>
  )
}
