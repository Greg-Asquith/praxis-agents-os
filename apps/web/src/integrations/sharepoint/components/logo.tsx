// apps/web/src/integrations/sharepoint/components/logo.tsx

import type { SVGProps } from "react"

import sharePointLogoUrl from "./sharepoint.svg"

export function SharePointLogo(props: SVGProps<SVGSVGElement>) {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" {...props}>
      <image href={sharePointLogoUrl} width="24" height="24" />
    </svg>
  )
}
