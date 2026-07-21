// apps/web/src/features/integrations/components/provider-catalog.tsx

import { useEffect } from "react"
import { PlugZapIcon } from "lucide-react"

import { EmptyState } from "@/components/ui/empty-state"
import { useIntegrationConnectionsQuery } from "@/features/integrations/api/list-connections"
import { useIntegrationProvidersQuery } from "@/features/integrations/api/list-providers"
import { ProviderCard } from "@/features/integrations/components/provider-card"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { loadIntegrationUiModules } from "@/integrations/registry"

export function ProviderCatalog() {
  const { workspace } = useActiveWorkspace()
  const { data: providers } = useIntegrationProvidersQuery()
  const { data: connections } = useIntegrationConnectionsQuery()
  const role = workspace.current_user_role
  const canWrite = role !== null && role !== "read_only"
  const canManageWorkspace = role === "owner" || role === "admin"
  const providerKeySignature = providers.map((provider) => provider.provider_key).join("|")

  useEffect(() => {
    void loadIntegrationUiModules(providerKeySignature ? providerKeySignature.split("|") : [])
  }, [providerKeySignature])

  if (providers.length === 0) {
    return (
      <EmptyState
        description="No providers are enabled for this deployment. Ask your administrator to configure one."
        icon={<PlugZapIcon className="size-5" />}
        title="No integration providers"
      />
    )
  }

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      {providers.map((provider) => (
        <ProviderCard
          canManageWorkspace={canManageWorkspace}
          canWrite={canWrite}
          connections={connections.items.filter(
            (connection) => connection.provider_key === provider.provider_key
          )}
          key={provider.provider_key}
          provider={provider}
        />
      ))}
    </div>
  )
}
