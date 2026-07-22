// apps/web/src/features/integrations/routes/integration-provider-route.tsx

import { useEffect } from "react"
import { getRouteApi, useNavigate } from "@tanstack/react-router"

import { PageHeader } from "@/components/shell/page-header"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { AddAccountButton } from "@/features/integrations/components/add-account-button"
import { ConnectionList } from "@/features/integrations/components/connection-list"
import { useIntegrationConnectionsQuery } from "@/features/integrations/api/list-connections"
import { useIntegrationProvidersQuery } from "@/features/integrations/api/list-providers"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { useIntegrationUiModule } from "@/integrations/registry"

const routeApi = getRouteApi("/app/integrations/$providerKey")

export function IntegrationProviderRoute() {
  const { providerKey } = routeApi.useParams()
  const search = routeApi.useSearch()
  const navigate = useNavigate()
  const { workspace } = useActiveWorkspace()
  const { data: providers } = useIntegrationProvidersQuery()
  const { data: connections } = useIntegrationConnectionsQuery()
  const module = useIntegrationUiModule(providerKey)
  const provider = providers.find((item) => item.provider_key === providerKey)

  useEffect(() => {
    if (!search.integration_error && !search.integration_status) {
      return
    }
    void navigate({
      params: { providerKey },
      replace: true,
      search: {},
      to: "/integrations/$providerKey",
    })
  }, [navigate, providerKey, search.integration_error, search.integration_status])

  if (!provider) {
    throw new Error("Integration provider route loaded without its provider.")
  }

  const role = workspace.current_user_role
  const canWrite = role !== null && role !== "read_only"
  const canManageWorkspace = role === "owner" || role === "admin"
  const available = Object.values(provider.configured_auth_modes).some(Boolean)
  const canConnect =
    available && canWrite && (provider.owner_scope === "user" || canManageWorkspace)
  const providerConnections = connections.items.filter(
    (connection) => connection.provider_key === providerKey
  )
  const description =
    module?.catalogDescription ?? `Connect ${provider.display_name} accounts for agents to use.`
  const ConnectHelp = module?.ConnectHelp

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={canConnect ? <AddAccountButton provider={provider} /> : undefined}
        description={description}
        title={provider.display_name}
      />
      {search.integration_status === "connected" ? (
        <Alert>
          <AlertTitle>Connection authorized</AlertTitle>
          <AlertDescription>
            We are checking the account and finding what agents can use.
          </AlertDescription>
        </Alert>
      ) : null}
      {search.integration_error ? (
        <Alert variant="destructive">
          <AlertTitle>Connection not completed</AlertTitle>
          <AlertDescription>{search.integration_error}</AlertDescription>
        </Alert>
      ) : null}
      {!available ? (
        <Alert>
          <AlertTitle>Not available for this deployment</AlertTitle>
          <AlertDescription>Ask your administrator to set it up.</AlertDescription>
        </Alert>
      ) : null}
      <section className="flex flex-col gap-4" aria-labelledby="connected-accounts-heading">
        <div>
          <h2 id="connected-accounts-heading" className="font-heading text-lg font-medium">
            Connections
          </h2>
          <p className="text-muted-foreground mt-1 text-sm">
            Choose what agents can use from each connection.
          </p>
        </div>
        <ConnectionList
          canManageWorkspace={canManageWorkspace}
          canWrite={canWrite}
          connections={providerConnections}
          emptyAction={canConnect ? <AddAccountButton provider={provider} /> : undefined}
          provider={provider}
        />
      </section>
      {ConnectHelp ? (
        <section aria-label={`${provider.display_name} connection help`}>
          <ConnectHelp provider={provider} />
        </section>
      ) : null}
    </div>
  )
}
