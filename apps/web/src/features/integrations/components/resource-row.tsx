// apps/web/src/features/integrations/components/resource-row.tsx

import type { ReactNode } from "react"
import { Building2Icon, ChevronDownIcon, ChevronRightIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import {
  integrationResourceIsManagerAccount,
  integrationResourceIsRemoved,
} from "@/features/integrations/components/resource-selection-model"
import { formatIntegrationResourceValue } from "@/features/integrations/format"
import type { IntegrationResource } from "@/features/integrations/types"
import { cn } from "@/lib/utils"

export function ResourceRow({
  action,
  canEdit,
  checked,
  children,
  collapsed,
  onCheckedChange,
  onToggleCollapsed,
  providerKey,
  resource,
  selectionDisabled = false,
  selectionDisabledReasonId,
}: {
  action?: ReactNode
  canEdit: boolean
  checked: boolean
  children?: ReactNode
  collapsed: boolean
  onCheckedChange: (checked: boolean) => void
  onToggleCollapsed: () => void
  providerKey: string
  resource: IntegrationResource
  selectionDisabled?: boolean
  selectionDisabledReasonId?: string
}) {
  const removed = integrationResourceIsRemoved(resource)
  const managerAccount = integrationResourceIsManagerAccount(resource)
  const level = resource.metadata["level"]
  const indentation = typeof level === "number" ? Math.min(Math.max(level, 0), 5) * 16 : 0
  const resourceDisabled = !canEdit || removed || managerAccount
  const selectionControlDisabled = resourceDisabled || selectionDisabled
  const checkboxId = `integration-resource-${resource.id}`
  const rowClassName = cn(
    "min-w-0 border-l border-transparent px-2 py-2 transition-colors",
    removed && "opacity-60",
    indentation > 0 && "border-l-border"
  )
  const rowStyle = { marginLeft: `${String(indentation)}px` }
  const displayName = formatIntegrationResourceValue(providerKey, resource.display_name)
  const externalId = formatIntegrationResourceValue(providerKey, resource.external_id)

  if (managerAccount) {
    return (
      <button
        aria-expanded={!collapsed}
        className={cn(
          rowClassName,
          "hover:bg-muted/60 flex w-auto cursor-pointer items-center gap-2.5 text-left"
        )}
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
            <span className="truncate text-sm font-medium">{displayName}</span>
            <Badge variant="secondary">Manager Account</Badge>
          </span>
          <span className="text-muted-foreground truncate font-mono text-xs">{externalId}</span>
        </span>
      </button>
    )
  }

  return (
    <div
      className={cn(
        rowClassName,
        "flex flex-col gap-1.5",
        !resourceDisabled && "hover:bg-muted/60"
      )}
      style={rowStyle}
    >
      <div className="flex min-w-0 items-center gap-2.5">
        <label
          className={cn(
            "flex min-w-0 flex-1 items-center gap-2.5",
            !selectionControlDisabled && "cursor-pointer"
          )}
          htmlFor={checkboxId}
        >
          <Checkbox
            aria-describedby={selectionDisabled ? selectionDisabledReasonId : undefined}
            aria-label={`Enable ${displayName}`}
            checked={checked}
            disabled={selectionControlDisabled}
            id={checkboxId}
            onCheckedChange={onCheckedChange}
          />
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="flex min-w-0 flex-wrap items-center gap-1.5">
              <span className="truncate text-sm font-medium">{displayName}</span>
              {removed ? <Badge variant="outline">No longer available</Badge> : null}
            </span>
            <span className="text-muted-foreground flex min-w-0 items-center gap-1.5 text-xs">
              <span className="truncate font-mono">{externalId}</span>
              {!resource.writable ? <span className="shrink-0">· Read Only</span> : null}
            </span>
          </span>
        </label>
        {action}
      </div>
      {children ? <div className="ml-6.5 flex flex-col gap-1.5">{children}</div> : null}
    </div>
  )
}
