// apps/web/src/features/integrations/components/connection-row.tsx

import { Suspense, useEffect, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import {
  ChevronDownIcon,
  ChevronRightIcon,
  EllipsisIcon,
  RefreshCwIcon,
  ShieldAlertIcon,
  Trash2Icon,
  WrenchIcon,
} from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import { useRefreshConnectionMutation } from "@/features/integrations/api/refresh-connection"
import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import { useRevokeConnectionMutation } from "@/features/integrations/api/revoke-connection"
import { useTestConnectionMutation } from "@/features/integrations/api/test-connection"
import { ConnectOAuthButton } from "@/features/integrations/components/connect-oauth-button"
import { ConnectionLabelEditor } from "@/features/integrations/components/connection-label-editor"
import { ConnectionStatusBadge } from "@/features/integrations/components/connection-status-badge"
import { connectionStatusPresentation } from "@/features/integrations/components/connection-status"
import { ResourceSelectionPanel } from "@/features/integrations/components/resource-selection-panel"
import { discoveryFinished } from "@/features/integrations/components/resource-discovery"
import { connectionResourcesAreEditable } from "@/features/integrations/components/resource-selection-model"
import {
  integrationAuthModeLabel,
  integrationOwnershipDescription,
} from "@/features/integrations/format"
import type { IntegrationConnection, IntegrationProvider } from "@/features/integrations/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formatDateTime } from "@/lib/format"

export function ConnectionRow({
  canEdit,
  connection,
  provider,
}: {
  canEdit: boolean
  connection: IntegrationConnection
  provider: IntegrationProvider
}) {
  const testMutation = useTestConnectionMutation()
  const queryClient = useQueryClient()
  const refreshMutation = useRefreshConnectionMutation()
  const revokeMutation = useRevokeConnectionMutation()
  const [expanded, setExpanded] = useState(connection.status === "needs_resource_selection")
  const [confirmRevoke, setConfirmRevoke] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const status = connectionStatusPresentation(connection.status)
  const canUseLifecycleActions = canEdit && connection.status !== "revoked"
  const canEditResources = connectionResourcesAreEditable(canEdit, connection.status)
  const previousStatus = useRef(connection.status)
  const hasMultipleAuthModes =
    Object.values(provider.configured_auth_modes).filter(Boolean).length > 1

  useEffect(() => {
    if (discoveryFinished(previousStatus.current, connection.status)) {
      void queryClient.invalidateQueries({
        queryKey: integrationsQueryKeys.resources(connection.id),
      })
    }
    previousStatus.current = connection.status
  }, [connection.id, connection.status, queryClient])

  async function runAction(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
    } catch (actionError) {
      setError(getErrorMessage(actionError))
    }
  }

  async function revoke() {
    await runAction(() => revokeMutation.mutateAsync(connection.id))
    setConfirmRevoke(false)
  }

  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="flex flex-col gap-3 p-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 flex-1 items-start gap-2.5">
          {provider.requires_discovery ? (
            <Button
              aria-expanded={expanded}
              aria-label={`${expanded ? "Hide" : "Show"} resources for ${connection.label}`}
              onClick={() => {
                setExpanded((current) => !current)
              }}
              size="icon-xs"
              type="button"
              variant="ghost"
            >
              {expanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
            </Button>
          ) : null}
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <ConnectionLabelEditor
                canEdit={canEdit}
                connectionId={connection.id}
                label={connection.label}
              />
              <ConnectionStatusBadge status={connection.status} />
            </div>
            <p className="text-muted-foreground text-xs">
              {integrationOwnershipDescription(connection.owner_scope)} · Added{" "}
              {formatDateTime(connection.created_at)}
              {hasMultipleAuthModes && connection.credential
                ? ` · ${integrationAuthModeLabel(connection.credential.auth_mode)}`
                : ""}
            </p>
            {connection.duplicate_of_connection_ids.length > 0 ? (
              <p className="text-warning-foreground flex items-center gap-1 text-xs">
                <ShieldAlertIcon className="size-3.5" aria-hidden="true" />
                This account is also connected elsewhere in this workspace.
              </p>
            ) : null}
            {error ? (
              <Alert className="mt-1" variant="destructive">
                <AlertTitle>Connection action failed</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2 pl-8 sm:pl-0">
          {status.action === "select_resources" ? (
            <Button
              onClick={() => {
                setExpanded(true)
              }}
              size="sm"
              type="button"
              variant="outline"
            >
              Choose Resources
            </Button>
          ) : null}
          {status.action === "retry_test" && canEdit ? (
            <Button
              disabled={testMutation.isPending}
              onClick={() => void runAction(() => testMutation.mutateAsync(connection.id))}
              size="sm"
              type="button"
              variant="outline"
            >
              Try Again
            </Button>
          ) : null}
          {status.action === "reauthenticate" &&
          canEdit &&
          provider.auth_modes.includes("oauth") ? (
            <ConnectOAuthButton
              connectionId={connection.id}
              connectionLabel={connection.label}
              provider={provider}
            />
          ) : null}
          {canUseLifecycleActions ? (
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <Button
                    aria-label={`Actions for ${connection.label}`}
                    size="icon-sm"
                    variant="ghost"
                  />
                }
              >
                <EllipsisIcon />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  disabled={testMutation.isPending}
                  onClick={() => void runAction(() => testMutation.mutateAsync(connection.id))}
                >
                  <WrenchIcon />
                  Check Connection
                </DropdownMenuItem>
                <DropdownMenuItem
                  disabled={refreshMutation.isPending}
                  onClick={() => void runAction(() => refreshMutation.mutateAsync(connection.id))}
                >
                  <RefreshCwIcon />
                  Refresh Access
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => {
                    setConfirmRevoke(true)
                  }}
                  variant="destructive"
                >
                  <Trash2Icon />
                  Disconnect
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
        </div>
      </div>
      {expanded && provider.requires_discovery ? (
        <Suspense fallback={<Skeleton className="m-4 h-40" />}>
          <ResourceSelectionPanel canEdit={canEditResources} connection={connection} />
        </Suspense>
      ) : null}
      <ConfirmDialog
        confirmIcon={<Trash2Icon data-icon="inline-start" />}
        confirmLabel="Disconnect"
        confirmPendingLabel="Disconnecting"
        description={`Disconnect '${connection.label}'? Agents will lose access to its resources.`}
        isPending={revokeMutation.isPending}
        onConfirm={revoke}
        onOpenChange={setConfirmRevoke}
        open={confirmRevoke}
        title="Disconnect this account?"
      />
    </div>
  )
}
