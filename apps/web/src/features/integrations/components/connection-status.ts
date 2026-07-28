// apps/web/src/features/integrations/components/connection-status.ts

type ConnectionStatusAction =
  "replace_credential" | "select_resources" | "reauthenticate" | "retry_discovery" | "retry_test"

export type ConnectionStatusPresentation = {
  action: ConnectionStatusAction | null
  label: string
  pending: boolean
  variant: "default" | "secondary" | "destructive" | "success" | "warning" | "outline"
}

const CONNECTION_STATUS_PRESENTATIONS = {
  auth_pending: { action: null, label: "Connecting…", pending: true, variant: "secondary" },
  discovery_pending: {
    action: null,
    label: "Finding your accounts…",
    pending: true,
    variant: "secondary",
  },
  discovery_stalled: {
    action: "retry_discovery",
    label: "Setup needs attention",
    pending: false,
    variant: "warning",
  },
  needs_resource_selection: {
    action: "select_resources",
    label: "Choose what agents can use",
    pending: false,
    variant: "warning",
  },
  active: { action: null, label: "Active", pending: false, variant: "success" },
  degraded: {
    action: "retry_discovery",
    label: "Limited access",
    pending: false,
    variant: "warning",
  },
  revoked: { action: null, label: "Disconnected", pending: false, variant: "outline" },
} satisfies Record<string, ConnectionStatusPresentation>

export function connectionStatusPresentation({
  authMode,
  discoveryStalled = false,
  status,
  supportsDiscovery = false,
}: {
  authMode?: string | undefined
  discoveryStalled?: boolean
  status: string
  supportsDiscovery?: boolean
}): ConnectionStatusPresentation {
  if (discoveryStalled) {
    return CONNECTION_STATUS_PRESENTATIONS.discovery_stalled
  }
  if (status === "needs_reauth") {
    return authMode === "oauth"
      ? {
          action: "reauthenticate",
          label: "Sign in again",
          pending: false,
          variant: "destructive",
        }
      : needsAttention()
  }
  if (status === "needs_credential") {
    if (authMode === "api_key") {
      return {
        action: "replace_credential",
        label: "Replace API key",
        pending: false,
        variant: "destructive",
      }
    }
    if (authMode === "service_account") {
      return {
        action: "replace_credential",
        label: "Replace Service Account Key",
        pending: false,
        variant: "destructive",
      }
    }
    return needsAttention()
  }
  if (status === "error") {
    return {
      ...needsAttention(),
      action: supportsDiscovery ? "retry_discovery" : "retry_test",
    }
  }
  if (status === "degraded" && !supportsDiscovery) {
    return { ...CONNECTION_STATUS_PRESENTATIONS.degraded, action: null }
  }
  if (status in CONNECTION_STATUS_PRESENTATIONS) {
    return CONNECTION_STATUS_PRESENTATIONS[status as keyof typeof CONNECTION_STATUS_PRESENTATIONS]
  }
  return needsAttention()
}

function needsAttention(): ConnectionStatusPresentation {
  return {
    action: null,
    label: "Needs attention",
    pending: false,
    variant: "destructive",
  }
}
