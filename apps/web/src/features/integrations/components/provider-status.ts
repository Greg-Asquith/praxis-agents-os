// apps/web/src/features/integrations/components/provider-status.ts

import type { IntegrationConnection, IntegrationProvider } from "@/features/integrations/types"
import { discoveryNeedsRecovery } from "@/features/integrations/components/resource-discovery"

type ProviderSummaryVariant = "destructive" | "secondary" | "success" | "warning"

export type ProviderSummaryStatus = {
  label: string
  tone: "attention" | "connected" | "pending" | "quiet" | "unavailable"
  variant: ProviderSummaryVariant | null
}

export function providerSummaryStatus(
  provider: IntegrationProvider,
  connections: readonly IntegrationConnection[]
): ProviderSummaryStatus {
  const currentConnections = connections.filter((connection) => connection.status !== "revoked")
  const statuses = new Set(currentConnections.map((connection) => connection.status))

  if (
    statuses.has("needs_reauth") ||
    statuses.has("needs_credential") ||
    statuses.has("error") ||
    currentConnections.some(discoveryNeedsRecovery)
  ) {
    return { label: "Needs attention", tone: "attention", variant: "destructive" }
  }

  if (
    statuses.has("auth_pending") ||
    statuses.has("discovery_pending") ||
    statuses.has("needs_resource_selection")
  ) {
    return { label: "Setting up…", tone: "pending", variant: "warning" }
  }

  if (statuses.has("active") || statuses.has("degraded")) {
    const count = currentConnections.length
    return {
      label: `Connected · ${String(count)} ${count === 1 ? "account" : "accounts"}`,
      tone: "connected",
      variant: "success",
    }
  }

  if (!Object.values(provider.configured_auth_modes).some(Boolean)) {
    return { label: "Not available", tone: "unavailable", variant: "secondary" }
  }

  return { label: "Not connected", tone: "quiet", variant: null }
}
