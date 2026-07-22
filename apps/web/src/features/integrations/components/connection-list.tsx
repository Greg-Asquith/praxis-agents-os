// apps/web/src/features/integrations/components/connection-list.tsx

import type { ReactNode } from "react"

import { EmptyState } from "@/components/ui/empty-state"
import { ConnectionRow } from "@/features/integrations/components/connection-row"
import type { IntegrationConnection, IntegrationProvider } from "@/features/integrations/types"

export function ConnectionList({
  canManageWorkspace,
  canWrite,
  connections,
  emptyAction,
  provider,
}: {
  canManageWorkspace: boolean
  canWrite: boolean
  connections: IntegrationConnection[]
  emptyAction?: ReactNode
  provider: IntegrationProvider
}) {
  if (connections.length === 0) {
    return (
      <EmptyState
        action={emptyAction}
        description={`Add one to let agents use ${provider.display_name}.`}
        size="compact"
        title="No connections yet"
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
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
