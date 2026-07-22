// apps/web/src/features/integrations/components/provider-card.tsx

import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { ApiKeyConnectDialog } from "@/features/integrations/components/api-key-connect-dialog"
import { ConnectOAuthButton } from "@/features/integrations/components/connect-oauth-button"
import { ConnectionList } from "@/features/integrations/components/connection-list"
import { ServiceAccountConnectDialog } from "@/features/integrations/components/service-account-connect-dialog"
import { integrationOwnerScopeLabel } from "@/features/integrations/format"
import type { IntegrationConnection, IntegrationProvider } from "@/features/integrations/types"

export function ProviderCard({
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
  const available = Object.values(provider.configured_auth_modes).some(Boolean)
  const canConnect =
    available && canWrite && (provider.owner_scope === "user" || canManageWorkspace)

  return (
    <Card className={!available ? "opacity-75" : undefined}>
      <CardHeader>
        <CardTitle>{provider.display_name}</CardTitle>
        <CardDescription>
          {available
            ? `${integrationOwnerScopeLabel(provider.owner_scope)} connection`
            : "Not configured for this deployment"}
        </CardDescription>
        <CardAction>
          <Badge variant={available ? "success" : "secondary"}>
            {available ? "Available" : "Unavailable"}
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <ConnectionList
          canManageWorkspace={canManageWorkspace}
          canWrite={canWrite}
          connections={connections}
          provider={provider}
        />
        {canConnect ? (
          <div className="flex flex-col gap-2 border-t pt-4">
            {provider.auth_modes.length > 1 ? (
              <p className="text-muted-foreground text-xs">
                Add another connection using either authentication method.
              </p>
            ) : null}
            <div className="flex flex-wrap items-center gap-2">
              {provider.configured_auth_modes["oauth"] ? (
                <ConnectOAuthButton provider={provider} />
              ) : null}
              {provider.configured_auth_modes["service_account"] ? (
                <ServiceAccountConnectDialog provider={provider} />
              ) : null}
              {provider.configured_auth_modes["api_key"] ? (
                <ApiKeyConnectDialog provider={provider} />
              ) : null}
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
