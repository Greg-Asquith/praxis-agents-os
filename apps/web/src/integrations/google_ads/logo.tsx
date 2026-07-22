// apps/web/src/integrations/google_ads/logo.tsx

import type { SVGProps } from "react"

export function GoogleAdsLogo(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 36 32" focusable="false" {...props}>
      <path
        fill="#4285f4"
        d="M14.2 3.2a5.3 5.3 0 0 1 9.2 0l11.4 19.7a5.3 5.3 0 0 1-9.2 5.3L14.2 8.5a5.3 5.3 0 0 1 0-5.3Z"
      />
      <path
        fill="#fbbc04"
        d="M14.2 3.2a5.3 5.3 0 0 1 9.2 5.3L12 28.2a5.3 5.3 0 0 1-9.2-5.3L14.2 3.2Z"
      />
      <circle cx="7.4" cy="25.5" r="5.3" fill="#34a853" />
    </svg>
  )
}
