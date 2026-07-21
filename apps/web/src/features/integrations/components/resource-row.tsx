// apps/web/src/features/integrations/components/resource-row.tsx

import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import {
  integrationResourceIsManagerAccount,
  integrationResourceIsRemoved,
} from "@/features/integrations/components/resource-selection-model"
import type { IntegrationResource } from "@/features/integrations/types"

export function ResourceRow({
  canEdit,
  checked,
  onCheckedChange,
  resource,
}: {
  canEdit: boolean
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  resource: IntegrationResource
}) {
  const removed = integrationResourceIsRemoved(resource)
  const managerAccount = integrationResourceIsManagerAccount(resource)
  const level = resource.metadata["level"]
  const indentation = typeof level === "number" ? Math.min(Math.max(level, 0), 5) * 16 : 0
  const disabled = !canEdit || removed || managerAccount

  return (
    <div
      className="hover:bg-muted/40 flex min-w-0 items-start gap-3 rounded-md px-2 py-2.5 transition-colors"
      style={{ paddingLeft: `${String(8 + indentation)}px` }}
    >
      <Checkbox
        aria-label={`Enable ${resource.display_name}`}
        checked={checked}
        className="mt-0.5"
        disabled={disabled}
        onCheckedChange={onCheckedChange}
      />
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="flex min-w-0 flex-wrap items-center gap-1.5">
          <span className="truncate text-sm font-medium">{resource.display_name}</span>
          {!resource.writable ? <Badge variant="outline">Read only</Badge> : null}
          {managerAccount ? <Badge variant="secondary">Manager account</Badge> : null}
          {removed ? <Badge variant="outline">No longer available</Badge> : null}
        </span>
        <span className="text-muted-foreground truncate font-mono text-xs">
          {resource.external_id}
        </span>
      </span>
    </div>
  )
}
