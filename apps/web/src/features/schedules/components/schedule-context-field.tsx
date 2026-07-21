// apps/web/src/features/schedules/components/schedule-context-field.tsx

import { Field, FieldDescription, FieldLabel } from "@/components/ui/field"
import { ContextSelect } from "@/features/integrations/components/context-select"
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
  return (
    <Field>
      <FieldLabel htmlFor="schedule-active-context">Active context</FieldLabel>
      <ContextSelect
        contextGroups={contextGroups}
        id="schedule-active-context"
        onChange={onChange}
        resources={resources}
        value={value}
      />
      <FieldDescription>
        Integration tools use this group or resource for every scheduled run.
      </FieldDescription>
    </Field>
  )
}
