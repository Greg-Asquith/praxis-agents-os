// apps/web/src/features/integrations/components/connection-status-badge.tsx

import { LoaderCircleIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { connectionStatusPresentation } from "@/features/integrations/components/connection-status"

export function ConnectionStatusBadge({ status }: { status: string }) {
  const presentation = connectionStatusPresentation(status)
  return (
    <Badge variant={presentation.variant}>
      {presentation.pending ? (
        <LoaderCircleIcon className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
      ) : null}
      {presentation.label}
    </Badge>
  )
}
