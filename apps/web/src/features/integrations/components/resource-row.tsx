// apps/web/src/features/integrations/components/resource-row.tsx

import { Building2Icon, ChevronDownIcon, ChevronRightIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import {
  integrationResourceIsManagerAccount,
  integrationResourceIsRemoved,
} from "@/features/integrations/components/resource-selection-model"
import type { IntegrationResource } from "@/features/integrations/types"
import { cn } from "@/lib/utils"

export function ResourceRow({
  canEdit,
  checked,
  collapsed,
  onCheckedChange,
  onToggleCollapsed,
  resource,
}: {
  canEdit: boolean
  checked: boolean
  collapsed: boolean
  onCheckedChange: (checked: boolean) => void
  onToggleCollapsed: () => void
  resource: IntegrationResource
}) {
  const removed = integrationResourceIsRemoved(resource)
  const managerAccount = integrationResourceIsManagerAccount(resource)
  const level = resource.metadata["level"]
  const indentation = typeof level === "number" ? Math.min(Math.max(level, 0), 5) * 16 : 0
  const disabled = !canEdit || removed || managerAccount
  const checkboxId = `integration-resource-${resource.id}`
  const rowClassName = cn(
    "flex min-w-0 items-center gap-2.5 border-l border-transparent px-2 py-2 transition-colors",
    removed && "opacity-60",
    indentation > 0 && "border-l-border"
  )
  const rowStyle = { marginLeft: `${String(indentation)}px` }

  if (managerAccount) {
    return (
      <button
        aria-expanded={!collapsed}
        className={cn(rowClassName, "hover:bg-muted/60 w-auto cursor-pointer text-left")}
        onClick={onToggleCollapsed}
        style={rowStyle}
        type="button"
      >
        <span className="bg-muted text-muted-foreground flex size-5 shrink-0 items-center justify-center rounded-md">
          {collapsed ? (
            <ChevronRightIcon className="size-3.5" aria-hidden="true" />
          ) : (
            <ChevronDownIcon className="size-3.5" aria-hidden="true" />
          )}
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="flex min-w-0 flex-wrap items-center gap-1.5">
            <Building2Icon className="text-muted-foreground size-3.5" aria-hidden="true" />
            <span className="truncate text-sm font-medium">{resource.display_name}</span>
            <Badge variant="secondary">Manager Account</Badge>
          </span>
          <span className="text-muted-foreground truncate font-mono text-xs">
            {resource.external_id}
          </span>
        </span>
      </button>
    )
  }

  return (
    <label
      className={cn(rowClassName, !disabled && "hover:bg-muted/60 cursor-pointer")}
      htmlFor={checkboxId}
      style={rowStyle}
    >
      <Checkbox
        aria-label={`Enable ${resource.display_name}`}
        checked={checked}
        disabled={disabled}
        id={checkboxId}
        onCheckedChange={onCheckedChange}
      />
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex min-w-0 flex-wrap items-center gap-1.5">
          <span className="truncate text-sm font-medium">{resource.display_name}</span>
          {removed ? <Badge variant="outline">No longer available</Badge> : null}
        </span>
        <span className="text-muted-foreground flex min-w-0 items-center gap-1.5 text-xs">
          <span className="truncate font-mono">{resource.external_id}</span>
          {!resource.writable ? <span className="shrink-0">· Read Only</span> : null}
        </span>
      </span>
    </label>
  )
}
