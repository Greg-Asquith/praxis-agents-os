// apps/web/src/features/integrations/components/connection-status-badge.tsx

import { LoaderCircleIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { connectionStatusPresentation } from "@/features/integrations/components/connection-status"
import type { IntegrationConnection } from "@/features/integrations/types"

export function ConnectionStatusBadge({
  connection,
  discoveryStalled,
  supportsDiscovery,
}: {
  connection: IntegrationConnection
  discoveryStalled: boolean
  supportsDiscovery: boolean
}) {
  const presentation = connectionStatusPresentation({
    authMode: connection.credential?.auth_mode,
    discoveryStalled,
    status: connection.status,
    supportsDiscovery,
  })
  return (
    <Badge variant={presentation.variant}>
      {presentation.pending ? (
        <LoaderCircleIcon className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
      ) : null}
      {presentation.label}
    </Badge>
  )
}
