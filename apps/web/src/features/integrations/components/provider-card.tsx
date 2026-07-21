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
import {
  integrationAuthModeLabel,
  integrationOwnerScopeLabel,
} from "@/features/integrations/format"
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
  const canConnect =
    provider.configured && canWrite && (provider.owner_scope === "user" || canManageWorkspace)

  return (
    <Card className={!provider.configured ? "opacity-75" : undefined}>
      <CardHeader>
        <CardTitle>{provider.display_name}</CardTitle>
        <CardDescription>
          {provider.configured
            ? `${integrationOwnerScopeLabel(provider.owner_scope)} connection`
            : "Not configured for this deployment"}
        </CardDescription>
        <CardAction>
          <div className="flex flex-wrap justify-end gap-1.5">
            {provider.auth_modes.map((authMode) => (
              <Badge key={authMode} variant="outline">
                {integrationAuthModeLabel(authMode)}
              </Badge>
            ))}
            <Badge variant={provider.configured ? "success" : "secondary"}>
              {provider.configured ? "Available" : "Unavailable"}
            </Badge>
          </div>
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
          <div className="flex flex-wrap items-center gap-2">
            {provider.auth_modes.includes("oauth") ? (
              <ConnectOAuthButton provider={provider} />
            ) : null}
            {provider.auth_modes.includes("api_key") ? (
              <ApiKeyConnectDialog provider={provider} />
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
