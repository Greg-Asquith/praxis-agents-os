// apps/web/src/integrations/outlook_mail/components/logo.tsx

import type { SVGProps } from "react"

import outlookLogoUrl from "./outlook.svg"

export function OutlookMailLogo(props: SVGProps<SVGSVGElement>) {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" {...props}>
      <image href={outlookLogoUrl} width="24" height="24" />
    </svg>
  )
}
