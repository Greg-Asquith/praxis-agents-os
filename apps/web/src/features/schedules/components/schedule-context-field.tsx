// apps/web/src/features/schedules/components/schedule-context-field.tsx

import { Field, FieldDescription, FieldLabel } from "@/components/ui/field"
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
  activeContextSelectionKey,
  contextGroupSelectionKey,
  resourceSelectionKey,
} from "@/features/integrations/active-context"
import type {
  ActiveContextSelectionValue,
  IntegrationContextGroup,
  IntegrationResource,
} from "@/features/integrations/types"

export function ScheduleContextField({
  contextGroups,
  onChange,
  resources,
  value,
}: {
  contextGroups: IntegrationContextGroup[]
  onChange: (value: ActiveContextSelectionValue | null) => void
  resources: IntegrationResource[]
  value: ActiveContextSelectionValue | null
}) {
  const enabledResources = resources.filter(
    (resource) => resource.enabled && resource.availability === "available"
  )
  const selectionKey = activeContextSelectionKey(value)
  const selectionAvailable =
    value === null ||
    (value.type === "context_group"
      ? contextGroups.some((group) => group.id === value.context_group_id)
      : enabledResources.some((resource) => resource.id === value.integration_resource_id))

  return (
    <Field>
      <FieldLabel htmlFor="schedule-active-context">Active context</FieldLabel>
      <Select
        onValueChange={(nextValue) => {
          if (nextValue === null || nextValue === activeContextSelectionKey(null)) {
            onChange(null)
            return
          }
          const group = contextGroups.find(
            (item) => contextGroupSelectionKey(item.id) === nextValue
          )
          if (group) {
            onChange({ type: "context_group", context_group_id: group.id })
            return
          }
          const resource = enabledResources.find(
            (item) => resourceSelectionKey(item.id) === nextValue
          )
          if (resource) {
            onChange({ type: "resource", integration_resource_id: resource.id })
          }
        }}
        value={selectionKey}
      >
        <SelectTrigger className="w-full" id="schedule-active-context">
          <SelectValue placeholder="No active context" />
        </SelectTrigger>
        <SelectContent align="start">
          <SelectGroup>
            <SelectItem value={activeContextSelectionKey(null)}>No active context</SelectItem>
          </SelectGroup>
          {contextGroups.length > 0 ? (
            <SelectGroup>
              <SelectLabel>Context groups</SelectLabel>
              {contextGroups.map((group) => (
                <SelectItem key={group.id} value={contextGroupSelectionKey(group.id)}>
                  {group.name}
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
                  label={`${resource.display_name} — ${resource.connection_label ?? "Connection"}`}
                  value={resourceSelectionKey(resource.id)}
                >
                  <span className="min-w-0 truncate">{resource.display_name}</span>
                  <span className="text-muted-foreground truncate">
                    {resource.connection_label ?? "Connection"}
                  </span>
                </SelectItem>
              ))}
            </SelectGroup>
          ) : null}
          {!selectionAvailable ? (
            <SelectGroup>
              <SelectLabel>Unavailable</SelectLabel>
              <SelectItem value={selectionKey} disabled>
                Selected context is no longer available
              </SelectItem>
            </SelectGroup>
          ) : null}
        </SelectContent>
      </Select>
      <FieldDescription>
        Integration tools use this group or resource for every scheduled run.
      </FieldDescription>
    </Field>
  )
}
