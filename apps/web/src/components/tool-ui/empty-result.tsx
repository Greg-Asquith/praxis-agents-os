// apps/web/src/components/tool-ui/empty-result.tsx

import type { ReactNode } from "react"

export function EmptyResult({ children }: { children: ReactNode }) {
  return <p className="text-muted-foreground py-4 text-center text-sm">{children}</p>
}
