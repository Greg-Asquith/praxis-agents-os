// apps/web/src/integrations/outlook_mail/components/tool-heading.tsx

import { OutlookMailLogo } from "@/integrations/outlook_mail/components/logo"

export function OutlookToolHeading({ children }: { children: string }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2 text-sm font-medium">
      <OutlookMailLogo className="size-4 shrink-0" />
      <span className="truncate">{children}</span>
    </span>
  )
}
