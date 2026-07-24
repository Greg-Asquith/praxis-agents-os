// apps/web/src/integrations/airtable/components/tool-heading.tsx

import { AirtableLogo } from "@/integrations/airtable/components/logo"

export function AirtableToolHeading({ children }: { children: string }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <AirtableLogo className="size-4 shrink-0" />
      <span className="truncate">{children}</span>
    </span>
  )
}
