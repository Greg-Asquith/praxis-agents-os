// apps/web/src/features/integrations/components/connection-list.tsx

import { ConnectionRow } from "@/features/integrations/components/connection-row"
import type { IntegrationConnection, IntegrationProvider } from "@/features/integrations/types"

export function ConnectionList({
  canManageWorkspace,
  canWrite,
  connections,
  provider,
}: {
  canManageWorkspace: boolean
  canWrite: boolean
  connections: IntegrationConnection[]
  provider: IntegrationProvider
}) {
  if (connections.length === 0) {
    return (
      <p className="text-muted-foreground rounded-lg border border-dashed px-3 py-4 text-sm">
        No connections yet.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-2">
      {connections.map((connection) => (
        <ConnectionRow
          canEdit={canWrite && (connection.owner_scope === "user" || canManageWorkspace)}
          connection={connection}
          key={connection.id}
          provider={provider}
        />
      ))}
    </div>
  )
}
