// apps/web/src/integrations/gmail/components/tool-heading.tsx

import { GmailLogo } from "@/integrations/gmail/components/logo"

export function GmailToolHeading({ children }: { children: string }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <GmailLogo className="size-4 shrink-0" />
      <span className="truncate">{children}</span>
    </span>
  )
}
