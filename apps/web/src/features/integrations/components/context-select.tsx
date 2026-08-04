// apps/web/src/features/integrations/components/context-select.tsx

import { useId } from "react"
import { Link } from "@tanstack/react-router"
import { ChevronDownIcon, Layers3Icon, Settings2Icon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover"
import {
  activeContextSelectionFromKey,
  activeContextSelectionKey,
  activeContextTargetsLabel,
  contextGroupSelectionKey,
  MAX_ACTIVE_CONTEXT_TARGETS,
  resourceSelectionKey,
  toggleActiveContextTarget,
} from "@/features/integrations/active-context"
import { ProviderMark } from "@/features/integrations/components/provider-mark"
import { formatIntegrationResourceValue } from "@/features/integrations/format"
import type {
  ActiveContextSelectionValue,
  IntegrationContextGroup,
  IntegrationResource,
} from "@/features/integrations/types"
import { titleCaseToken } from "@/lib/format"
import { cn } from "@/lib/utils"

export function ContextSelect({
  compact = false,
  compactTitle = "Active context · applies to the next run in this conversation",
  contextGroups,
  disabled = false,
  hasUnavailable = false,
  id,
  onChange,
  resources,
  showManageIntegrations = false,
  showPersonalBadges = false,
  value,
}: {
  compact?: boolean
  compactTitle?: string
  contextGroups: IntegrationContextGroup[]
  disabled?: boolean
  hasUnavailable?: boolean
  id?: string
  onChange: (value: ActiveContextSelectionValue[]) => void
  resources: IntegrationResource[]
  showManageIntegrations?: boolean
  showPersonalBadges?: boolean
  value: ActiveContextSelectionValue[]
}) {
  const optionIdPrefix = useId()
  const enabledResources = resources.filter(
    (resource) =>
      resource.enabled &&
      resource.availability === "available" &&
      (resource.connection_status === undefined ||
        resource.connection_status === "active" ||
        resource.connection_status === "degraded")
  )
  const selectedKeys = new Set(value.map(activeContextSelectionKey))
  const availableKeys = new Set([
    ...contextGroups.map((group) => contextGroupSelectionKey(group.id)),
    ...enabledResources.map((resource) => resourceSelectionKey(resource.id)),
  ])
  const unavailableTargets = value.filter(
    (target) => !availableKeys.has(activeContextSelectionKey(target))
  )
  const selectionLabel = activeContextTargetsLabel(value, contextGroups, enabledResources)
  const atLimit = value.length >= MAX_ACTIVE_CONTEXT_TARGETS

  function toggleTarget(key: string) {
    const target = activeContextSelectionFromKey(key, contextGroups, enabledResources)
    if (target) {
      onChange(toggleActiveContextTarget(value, target))
    }
  }

  function removeUnavailableTarget(target: ActiveContextSelectionValue) {
    const targetKey = activeContextSelectionKey(target)
    onChange(value.filter((item) => activeContextSelectionKey(item) !== targetKey))
  }

  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            aria-label={compact ? `Active integration context: ${selectionLabel}` : undefined}
            className={cn(
              "justify-between font-normal",
              compact
                ? "hover:bg-muted max-w-72 gap-1.5 border-0 px-2 shadow-none focus-visible:border-transparent"
                : "w-full"
            )}
            disabled={disabled}
            id={id}
            size={compact ? "sm" : "default"}
            title={compact ? compactTitle : undefined}
            type="button"
            variant={compact ? "ghost" : "outline"}
          />
        }
      >
        <span className="flex min-w-0 items-center gap-1.5">
          {compact ? (
            <Layers3Icon className="text-muted-foreground" data-icon="inline-start" />
          ) : null}
          <span className="truncate">
            {value.length === 0 ? "No Active Context" : selectionLabel}
          </span>
          {hasUnavailable || unavailableTargets.length > 0 ? (
            <span
              aria-label="Some active context resources are unavailable"
              className="bg-warning size-2 shrink-0 rounded-full"
            />
          ) : null}
        </span>
        <ChevronDownIcon className="text-muted-foreground" data-icon="inline-end" />
      </PopoverTrigger>
      <PopoverContent
        align={compact ? "start" : "end"}
        className="max-h-(--available-height) w-[min(24rem,calc(100vw-1rem))] gap-0 overflow-hidden overscroll-contain p-0"
      >
        <PopoverHeader className="border-b px-3 py-2.5">
          <PopoverTitle>Active context</PopoverTitle>
          <PopoverDescription>
            Choose up to {MAX_ACTIVE_CONTEXT_TARGETS} groups or resources for each run.
          </PopoverDescription>
        </PopoverHeader>
        <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
          {contextGroups.length > 0 ? (
            <ContextOptionSection label="Context Groups">
              {contextGroups.map((group) => {
                const key = contextGroupSelectionKey(group.id)
                return (
                  <ContextOption
                    checked={selectedKeys.has(key)}
                    disabled={disabled || (atLimit && !selectedKeys.has(key))}
                    id={`${optionIdPrefix}-${key}`}
                    key={group.id}
                    onToggle={() => {
                      toggleTarget(key)
                    }}
                  >
                    <Layers3Icon className="text-muted-foreground mt-0.5 size-4 shrink-0" />
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span className="truncate">{group.name}</span>
                      <span className="text-muted-foreground text-xs">
                        {contextGroupSizeLabel(group)}
                      </span>
                    </span>
                  </ContextOption>
                )
              })}
            </ContextOptionSection>
          ) : null}
          {enabledResources.length > 0 ? (
            <ContextOptionSection label="Connected Resources">
              {enabledResources.map((resource) => {
                const key = resourceSelectionKey(resource.id)
                const displayName = formatIntegrationResourceValue(
                  resource.provider_key,
                  resource.display_name
                )
                const isPersonal = showPersonalBadges && resource.connection_owner_scope === "user"
                return (
                  <ContextOption
                    checked={selectedKeys.has(key)}
                    disabled={disabled || (atLimit && !selectedKeys.has(key))}
                    id={`${optionIdPrefix}-${key}`}
                    key={resource.id}
                    onToggle={() => {
                      toggleTarget(key)
                    }}
                  >
                    <ProviderMark
                      className="mt-0.5 shrink-0"
                      providerKey={resource.provider_key ?? "other"}
                    />
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="flex min-w-0 items-center gap-1.5">
                        <span className="truncate">{displayName}</span>
                        {isPersonal ? (
                          <Badge className="h-auto px-1.5 py-0 text-[0.65rem]" variant="secondary">
                            Personal — only you can use this
                          </Badge>
                        ) : null}
                      </span>
                      <span className="text-muted-foreground truncate text-xs">
                        {integrationResourceProviderLabel(resource)}
                        {resource.connection_label ? ` · ${resource.connection_label}` : ""}
                      </span>
                    </span>
                  </ContextOption>
                )
              })}
            </ContextOptionSection>
          ) : null}
          {unavailableTargets.length > 0 ? (
            <ContextOptionSection label="Unavailable">
              {unavailableTargets.map((target) => (
                <ContextOption
                  checked
                  disabled={disabled}
                  id={`${optionIdPrefix}-${activeContextSelectionKey(target)}`}
                  key={activeContextSelectionKey(target)}
                  onToggle={() => {
                    removeUnavailableTarget(target)
                  }}
                >
                  <span className="text-muted-foreground">Selected context is unavailable</span>
                </ContextOption>
              ))}
            </ContextOptionSection>
          ) : null}
          {contextGroups.length === 0 &&
          enabledResources.length === 0 &&
          unavailableTargets.length === 0 ? (
            <p className="text-muted-foreground px-2 py-4 text-center text-xs">
              No connected resources are ready yet.
            </p>
          ) : null}
        </div>
        <div className="text-muted-foreground flex items-center justify-between border-t px-2 py-1.5 text-xs">
          <span>
            {value.length} of {MAX_ACTIVE_CONTEXT_TARGETS} selected
          </span>
          {value.length > 0 ? (
            <Button
              disabled={disabled}
              onClick={() => {
                onChange([])
              }}
              size="xs"
              type="button"
              variant="ghost"
            >
              Clear
            </Button>
          ) : null}
        </div>
        {showManageIntegrations ? (
          <div className="border-t p-1.5">
            <Button
              className="w-full justify-start"
              render={<Link to="/integrations" />}
              size="sm"
              variant="ghost"
            >
              <Settings2Icon className="text-muted-foreground" data-icon="inline-start" />
              Manage Integrations
            </Button>
          </div>
        ) : null}
      </PopoverContent>
    </Popover>
  )
}

function ContextOptionSection({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <div className="py-1">
      <p className="text-muted-foreground px-2 py-1 text-xs font-medium">{label}</p>
      <div className="flex flex-col">{children}</div>
    </div>
  )
}

function ContextOption({
  checked,
  children,
  disabled = false,
  id,
  onToggle,
}: {
  checked: boolean
  children: React.ReactNode
  disabled?: boolean
  id: string
  onToggle: () => void
}) {
  return (
    <label
      className={cn(
        "hover:bg-muted flex min-h-10 cursor-pointer items-start gap-2 rounded-md px-2 py-1.5",
        disabled && "cursor-not-allowed opacity-50"
      )}
      htmlFor={id}
    >
      <Checkbox
        checked={checked}
        className="mt-0.5"
        disabled={disabled}
        id={id}
        onCheckedChange={onToggle}
      />
      {children}
    </label>
  )
}

function integrationResourceProviderLabel(resource: IntegrationResource) {
  return titleCaseToken(resource.provider_key ?? "other", "Provider")
}

function contextGroupSizeLabel(group: IntegrationContextGroup) {
  return group.members.length === 1 ? "1 resource" : `${String(group.members.length)} resources`
}
