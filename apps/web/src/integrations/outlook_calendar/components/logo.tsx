// apps/web/src/integrations/outlook_calendar/components/logo.tsx

import type { SVGProps } from "react"

import calendarLogoUrl from "./calendar.svg"

export function OutlookCalendarLogo(props: SVGProps<SVGSVGElement>) {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" {...props}>
      <image href={calendarLogoUrl} width="24" height="24" />
    </svg>
  )
}
