// apps/web/src/features/integrations/components/context-select.tsx

import { useNavigate } from "@tanstack/react-router"
import { Layers3Icon, Settings2Icon } from "lucide-react"

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  activeContextSelectionFromKey,
  activeContextSelectionKey,
  contextGroupSelectionKey,
  MANAGE_INTEGRATIONS_SELECTION,
  resourceSelectionKey,
} from "@/features/integrations/active-context"
import type {
  ActiveContextSelectionValue,
  IntegrationContextGroup,
  IntegrationResource,
} from "@/features/integrations/types"
import { titleCaseToken } from "@/lib/format"
import { cn } from "@/lib/utils"

export function ContextSelect({
  compact = false,
  contextGroups,
  disabled = false,
  hasUnavailable = false,
  id,
  onChange,
  resources,
  showManageIntegrations = false,
  value,
}: {
  compact?: boolean
  contextGroups: IntegrationContextGroup[]
  disabled?: boolean
  hasUnavailable?: boolean
  id?: string
  onChange: (value: ActiveContextSelectionValue | null) => void
  resources: IntegrationResource[]
  showManageIntegrations?: boolean
  value: ActiveContextSelectionValue | null
}) {
  const navigate = useNavigate()
  const enabledResources = resources.filter(
    (resource) =>
      resource.enabled &&
      resource.availability === "available" &&
      (resource.connection_status === undefined ||
        resource.connection_status === "active" ||
        resource.connection_status === "degraded")
  )
  const selectionKey = activeContextSelectionKey(value)
  const selectionAvailable =
    value === null ||
    (value.type === "context_group"
      ? contextGroups.some((group) => group.id === value.context_group_id)
      : enabledResources.some((resource) => resource.id === value.integration_resource_id))

  return (
    <Select
      disabled={disabled}
      onValueChange={(nextValue) => {
        if (nextValue === MANAGE_INTEGRATIONS_SELECTION) {
          void navigate({ to: "/integrations" })
          return
        }
        if (nextValue === null) {
          return
        }
        const selection = activeContextSelectionFromKey(nextValue, contextGroups, enabledResources)
        if (selection !== undefined) {
          onChange(selection)
        }
      }}
      value={selectionKey}
    >
      <SelectTrigger
        aria-label={compact ? "Active integration context" : undefined}
        className={cn(
          compact
            ? "hover:bg-muted max-w-48 gap-1.5 border-0 px-2 shadow-none focus-visible:border-transparent"
            : "w-full"
        )}
        id={id}
        size={compact ? "sm" : "default"}
        title={
          compact ? "Active context · applies to the next run in this conversation" : undefined
        }
      >
        {compact ? <Layers3Icon className="text-muted-foreground" /> : null}
        <SelectValue placeholder="No active context" />
        {compact && hasUnavailable ? (
          <span
            aria-label="Some active context resources are unavailable"
            className="bg-warning size-2 shrink-0 rounded-full"
          />
        ) : null}
      </SelectTrigger>
      <SelectContent align={compact ? "start" : "end"} className={compact ? "min-w-64" : undefined}>
        <SelectGroup>
          <SelectItem value={activeContextSelectionKey(null)}>No active context</SelectItem>
        </SelectGroup>
        {contextGroups.length > 0 ? (
          <SelectGroup>
            <SelectLabel>Context Groups</SelectLabel>
            {contextGroups.map((group) => (
              <SelectItem
                key={group.id}
                label={`${group.name} · ${String(group.members.length)} ${group.members.length === 1 ? "resource" : "resources"}`}
                value={contextGroupSelectionKey(group.id)}
              >
                <span className="min-w-0 truncate">{group.name}</span>
                <span className="text-muted-foreground text-xs">{group.members.length}</span>
              </SelectItem>
            ))}
          </SelectGroup>
        ) : null}
        {enabledResources.length > 0 ? (
          <SelectGroup>
            <SelectLabel>Connected resources</SelectLabel>
            {enabledResources.map((resource) => (
              <SelectItem
                key={resource.id}
                label={`${resource.display_name} · ${integrationResourceProviderLabel(resource)}`}
                value={resourceSelectionKey(resource.id)}
              >
                <span className="min-w-0 truncate">{resource.display_name}</span>
                <span className="text-muted-foreground truncate text-xs">
                  {integrationResourceProviderLabel(resource)}
                  {resource.connection_label ? ` · ${resource.connection_label}` : ""}
                </span>
              </SelectItem>
            ))}
          </SelectGroup>
        ) : null}
        {!selectionAvailable ? (
          <SelectGroup>
            <SelectLabel>Unavailable</SelectLabel>
            <SelectItem disabled value={selectionKey}>
              Selected context is no longer available
            </SelectItem>
          </SelectGroup>
        ) : null}
        {showManageIntegrations ? (
          <SelectGroup>
            <SelectLabel>Settings</SelectLabel>
            <SelectItem value={MANAGE_INTEGRATIONS_SELECTION}>
              <Settings2Icon />
              Manage integrations
            </SelectItem>
          </SelectGroup>
        ) : null}
      </SelectContent>
    </Select>
  )
}

function integrationResourceProviderLabel(resource: IntegrationResource) {
  return titleCaseToken(resource.provider_key ?? "other", "Provider")
}
