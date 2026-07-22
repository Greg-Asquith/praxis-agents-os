// apps/web/src/features/integrations/components/resource-selection-panel.tsx

import { useState } from "react"
import { RefreshCwIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { useRetryDiscoveryMutation } from "@/features/integrations/api/retry-discovery"
import { useIntegrationResourcesForConnectionQuery } from "@/features/integrations/api/list-resources"
import { useUpdateResourceSelectionMutation } from "@/features/integrations/api/update-resource-selection"
import { ResourceRow } from "@/features/integrations/components/resource-row"
import { discoveryStatusLabel } from "@/features/integrations/components/resource-discovery"
import {
  enabledSelectableResourceIds,
  resourcesInHierarchyOrder,
  resourcesWithExpandedParents,
} from "@/features/integrations/components/resource-selection-model"
import { integrationResourceTypeLabel } from "@/features/integrations/format"
import type { IntegrationConnection, IntegrationResource } from "@/features/integrations/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formatDateTime } from "@/lib/format"

export function ResourceSelectionPanel({
  canEdit,
  connection,
}: {
  canEdit: boolean
  connection: IntegrationConnection
}) {
  const { data: resources } = useIntegrationResourcesForConnectionQuery(connection.id)
  const signature = resources
    .map((resource) => `${resource.id}:${resource.enabled ? "1" : "0"}:${resource.availability}`)
    .join("|")

  return (
    <ResourceSelectionForm
      canEdit={canEdit}
      connection={connection}
      key={signature}
      resources={resources}
    />
  )
}

function ResourceSelectionForm({
  canEdit,
  connection,
  resources,
}: {
  canEdit: boolean
  connection: IntegrationConnection
  resources: IntegrationResource[]
}) {
  const saveMutation = useUpdateResourceSelectionMutation()
  const discoveryMutation = useRetryDiscoveryMutation()
  const [selected, setSelected] = useState(() => new Set(enabledSelectableResourceIds(resources)))
  const [collapsedManagers, setCollapsedManagers] = useState(() => new Set<string>())
  const [error, setError] = useState<string | null>(null)
  const initial = enabledSelectableResourceIds(resources).toSorted()
  const pending = [...selected].toSorted()
  const changed = initial.join("|") !== pending.join("|")
  const groups = groupResources(resources)
  const discoveryRun = connection.latest_discovery_run
  const discoveryPending = connection.status === "discovery_pending"

  async function save() {
    setError(null)
    try {
      await saveMutation.mutateAsync({
        connectionId: connection.id,
        enabledResourceIds: pending,
      })
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
    }
  }

  async function rediscover() {
    setError(null)
    try {
      await discoveryMutation.mutateAsync(connection.id)
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
    }
  }

  return (
    <div className="bg-muted/25 flex flex-col gap-4 border-t px-4 py-4">
      {connection.status === "needs_resource_selection" ? (
        <Alert>
          <AlertTitle>Choose what agents can use</AlertTitle>
          <AlertDescription>
            Choose at least one account before agents can use this connection.
          </AlertDescription>
        </Alert>
      ) : null}
      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Changes not saved</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      <div className="flex flex-col gap-4">
        {groups.length > 0 ? (
          groups.map(([resourceType, items]) => (
            <section className="flex min-h-0 flex-col gap-1" key={resourceType}>
              <h4 className="text-muted-foreground px-2 pb-1 text-xs font-medium tracking-wide uppercase">
                {integrationResourceTypeLabel(resourceType)}
              </h4>
              <div className="bg-background max-h-80 overflow-y-auto rounded-lg border p-1">
                {resourcesWithExpandedParents(items, collapsedManagers).map((resource) => (
                  <ResourceRow
                    canEdit={canEdit}
                    checked={selected.has(resource.id)}
                    collapsed={collapsedManagers.has(resource.external_id)}
                    key={resource.id}
                    onCheckedChange={(checked) => {
                      setSelected((current) => {
                        const next = new Set(current)
                        if (checked) {
                          next.add(resource.id)
                        } else {
                          next.delete(resource.id)
                        }
                        return next
                      })
                    }}
                    onToggleCollapsed={() => {
                      setCollapsedManagers((current) => {
                        const next = new Set(current)
                        if (next.has(resource.external_id)) {
                          next.delete(resource.external_id)
                        } else {
                          next.add(resource.external_id)
                        }
                        return next
                      })
                    }}
                    resource={resource}
                  />
                ))}
              </div>
            </section>
          ))
        ) : (
          <p className="text-muted-foreground px-2 text-sm">
            We have not found any resources for this account yet.
          </p>
        )}
      </div>
      <div className="flex flex-col gap-2 border-t pt-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-muted-foreground flex flex-col gap-0.5 text-xs">
          <span>
            {discoveryPending
              ? "Looking for resources…"
              : discoveryRun
                ? discoveryStatusLabel(discoveryRun.status)
                : "Resources have not been checked yet"}
          </span>
          {discoveryRun ? (
            <span>
              {discoveryRun.finished_at ? "Finished" : "Started"}{" "}
              {formatDateTime(discoveryRun.finished_at ?? discoveryRun.started_at)}
              {discoveryRun.status === "succeeded"
                ? ` · ${String(discoveryRun.resources_found)} resources found`
                : ""}
            </span>
          ) : null}
        </div>
        {canEdit ? (
          <div className="flex items-center gap-2">
            <Button
              disabled={discoveryMutation.isPending || discoveryPending}
              onClick={() => void rediscover()}
              size="sm"
              type="button"
              variant="outline"
            >
              <RefreshCwIcon
                className={
                  discoveryMutation.isPending ? "animate-spin motion-reduce:animate-none" : ""
                }
                data-icon="inline-start"
              />
              {discoveryMutation.isPending
                ? "Starting"
                : discoveryPending
                  ? "Discovery Running"
                  : "Look for New Resources"}
            </Button>
            <Button
              disabled={!changed || saveMutation.isPending}
              onClick={() => void save()}
              size="sm"
              type="button"
            >
              {saveMutation.isPending ? "Saving" : "Save Selection"}
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  )
}

function groupResources(resources: IntegrationResource[]) {
  const groups = new Map<string, IntegrationResource[]>()
  for (const resource of resources) {
    const items = groups.get(resource.resource_type) ?? []
    items.push(resource)
    groups.set(resource.resource_type, items)
  }
  return [...groups.entries()]
    .map(([resourceType, items]) => [resourceType, resourcesInHierarchyOrder(items)] as const)
    .toSorted(([left], [right]) => left.localeCompare(right))
}
