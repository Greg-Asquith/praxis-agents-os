// apps/web/src/features/schedules/components/schedule-context-field.tsx

import { Field, FieldDescription, FieldLabel } from "@/components/ui/field"
import { ContextSelect } from "@/features/integrations/components/context-select"
import type {
  ActiveContextSelectionValue,
  IntegrationContextGroup,
  IntegrationResource,
} from "@/features/integrations/types"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"

export function ScheduleContextField({
  contextGroups,
  onChange,
  resources,
  value,
}: {
  contextGroups: IntegrationContextGroup[]
  onChange: (value: ActiveContextSelectionValue[]) => void
  resources: IntegrationResource[]
  value: ActiveContextSelectionValue[]
}) {
  const { workspace } = useActiveWorkspace()

  return (
    <Field>
      <FieldLabel htmlFor="schedule-active-context">Active context</FieldLabel>
      <ContextSelect
        contextGroups={contextGroups}
        id="schedule-active-context"
        onChange={onChange}
        resources={resources}
        showPersonalBadges={!workspace.is_personal}
        value={value}
      />
      <FieldDescription>
        Integration tools use these groups and resources for every scheduled run.
      </FieldDescription>
    </Field>
  )
}
