import { useEffect } from "react"
import { Link } from "@tanstack/react-router"
import { ChevronRightIcon, PlugZapIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { EmptyState } from "@/components/ui/empty-state"
import { useIntegrationConnectionsQuery } from "@/features/integrations/api/list-connections"
import { useIntegrationProvidersQuery } from "@/features/integrations/api/list-providers"
import { providerSummaryStatus } from "@/features/integrations/components/provider-status"
import type { IntegrationConnection, IntegrationProvider } from "@/features/integrations/types"
import { loadIntegrationUiModules, useIntegrationUiModule } from "@/integrations/registry"
import { cn } from "@/lib/utils"

export function ProviderList() {
  const { data: providers } = useIntegrationProvidersQuery()
  const { data: connections } = useIntegrationConnectionsQuery()
  const providerKeySignature = providers.map((provider) => provider.provider_key).join("|")
  const connectionsByProvider = groupConnectionsByProvider(connections.items)

  useEffect(() => {
    void loadIntegrationUiModules(providerKeySignature ? providerKeySignature.split("|") : [])
  }, [providerKeySignature])

  if (providers.length === 0) {
    return (
      <EmptyState
        description="No providers are enabled for this deployment. Ask your administrator to set one up."
        icon={<PlugZapIcon className="size-5" />}
        title="No integration providers"
      />
    )
  }

  return (
    <div className="divide-border divide-y" aria-label="Integration providers">
      {providers.map((provider) => (
        <ProviderListRow
          connections={connectionsByProvider.get(provider.provider_key) ?? []}
          key={provider.provider_key}
          provider={provider}
        />
      ))}
    </div>
  )
}

function ProviderListRow({
  connections,
  provider,
}: {
  connections: IntegrationConnection[]
  provider: IntegrationProvider
}) {
  const module = useIntegrationUiModule(provider.provider_key)
  const Icon = module?.icons?.[provider.provider_key] ?? PlugZapIcon
  const status = providerSummaryStatus(provider, connections)
  const available = Object.values(provider.configured_auth_modes).some(Boolean)
  const description =
    module?.catalogDescription ?? `Connect ${provider.display_name} accounts for agents to use.`

  return (
    <Link
      className={cn(
        "focus-visible:ring-ring/50 group hover:bg-muted/45 flex min-h-20 items-center gap-3 rounded-lg px-2 py-4 transition-colors outline-none focus-visible:ring-[3px] sm:gap-4 sm:px-3",
        !available && "opacity-70"
      )}
      params={{ providerKey: provider.provider_key }}
      to="/integrations/$providerKey"
    >
      <span className="border-border bg-background flex size-10 shrink-0 items-center justify-center rounded-xl border shadow-xs">
        <Icon className="size-5" aria-hidden="true" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-medium">{provider.display_name}</span>
        <span className="text-muted-foreground mt-0.5 block truncate text-sm">{description}</span>
      </span>
      <span className="flex shrink-0 items-center gap-2">
        {status.variant ? (
          <Badge variant={status.variant}>{status.label}</Badge>
        ) : (
          <span className="text-muted-foreground text-xs">{status.label}</span>
        )}
        <ChevronRightIcon
          className="text-muted-foreground size-4 transition-transform group-hover:translate-x-0.5"
          aria-hidden="true"
        />
      </span>
    </Link>
  )
}

function groupConnectionsByProvider(connections: IntegrationConnection[]) {
  const grouped = new Map<string, IntegrationConnection[]>()
  for (const connection of connections) {
    const items = grouped.get(connection.provider_key) ?? []
    items.push(connection)
    grouped.set(connection.provider_key, items)
  }
  return grouped
}
