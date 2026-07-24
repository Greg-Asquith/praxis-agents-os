// apps/web/src/features/integrations/components/connection-status.ts

type ConnectionStatusAction =
  "select_resources" | "reauthenticate" | "retry_discovery" | "retry_test"

export type ConnectionStatusPresentation = {
  action: ConnectionStatusAction | null
  label: string
  pending: boolean
  variant: "default" | "secondary" | "destructive" | "success" | "warning" | "outline"
}

const CONNECTION_STATUS_PRESENTATIONS: Record<string, ConnectionStatusPresentation> = {
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
  degraded: { action: null, label: "Limited access", pending: false, variant: "warning" },
  error: {
    action: "retry_test",
    label: "Needs attention",
    pending: false,
    variant: "destructive",
  },
  revoked: { action: null, label: "Disconnected", pending: false, variant: "outline" },
  needs_reauth: {
    action: "reauthenticate",
    label: "Sign in again",
    pending: false,
    variant: "destructive",
  },
}

export function connectionStatusPresentation(status: string): ConnectionStatusPresentation {
  return (
    CONNECTION_STATUS_PRESENTATIONS[status] ?? {
      action: null,
      label: status,
      pending: false,
      variant: "outline",
    }
  )
}
