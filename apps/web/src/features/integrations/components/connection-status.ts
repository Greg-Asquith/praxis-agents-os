// apps/web/src/features/integrations/components/connection-status.ts

type ConnectionStatusAction = "select_resources" | "reauthenticate" | "retry_test"

export type ConnectionStatusPresentation = {
  action: ConnectionStatusAction | null
  label: string
  pending: boolean
  variant: "default" | "secondary" | "destructive" | "success" | "warning" | "outline"
}

const CONNECTION_STATUS_PRESENTATIONS: Record<string, ConnectionStatusPresentation> = {
  auth_pending: { action: null, label: "Connecting", pending: true, variant: "secondary" },
  discovery_pending: {
    action: null,
    label: "Finding resources",
    pending: true,
    variant: "secondary",
  },
  needs_resource_selection: {
    action: "select_resources",
    label: "Select resources",
    pending: false,
    variant: "warning",
  },
  active: { action: null, label: "Active", pending: false, variant: "success" },
  degraded: { action: null, label: "Limited", pending: false, variant: "warning" },
  error: {
    action: "retry_test",
    label: "Needs attention",
    pending: false,
    variant: "destructive",
  },
  revoked: { action: null, label: "Revoked", pending: false, variant: "outline" },
  needs_reauth: {
    action: "reauthenticate",
    label: "Reconnect",
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
