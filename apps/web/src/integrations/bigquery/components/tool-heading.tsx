// apps/web/src/integrations/bigquery/components/tool-heading.tsx

import { BigQueryLogo } from "@/integrations/bigquery/components/logo"

export function BigQueryToolHeading({ children }: { children: string }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <BigQueryLogo className="size-4 shrink-0" />
      <span className="truncate">{children}</span>
    </span>
  )
}
