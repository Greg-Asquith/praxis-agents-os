// apps/web/src/features/agents/components/agent-tool-provider-group.tsx

import { ChevronDownIcon, ChevronRightIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import type { AgentFormState } from "@/features/agents/components/agent-form-model"
import {
  planBulkToolModes,
  stripProviderPrefix,
  type ToolGroup,
} from "@/features/agents/components/agent-tool-catalog-utils"
import { AgentToolPolicyRow } from "@/features/agents/components/agent-tool-policy-row"
import { toolModeOptions, type RuntimeToolMode } from "@/features/agents/runtime-tools"
import { titleCaseToken } from "@/lib/format"
import { cn } from "@/lib/utils"

export function AgentToolProviderGroup({
  forceOpen,
  group,
  onModeChange,
  onModesChange,
  onOpenChange,
  openOverride,
  searchActive = false,
  toolModes,
}: {
  forceOpen: boolean
  group: ToolGroup
  onModeChange: (toolName: string, mode: RuntimeToolMode) => void
  onModesChange: (modes: Record<string, RuntimeToolMode>) => void
  onOpenChange: (open: boolean) => void
  openOverride: boolean | undefined
  searchActive?: boolean
  toolModes: AgentFormState["toolModes"]
}) {
  const activeCount = group.tools.filter((tool) => (toolModes[tool.name] ?? "off") !== "off").length
  const open = openOverride ?? forceOpen
  const providerLabel = titleCaseToken(group.provider, group.provider)
  const toolCount = group.tools.length
  const autoPlan = planBulkToolModes(group.tools, "auto")
  const scopeLabel = searchActive
    ? `Set the ${String(toolCount)} shown ${providerLabel} ${toolCount === 1 ? "tool" : "tools"} to`
    : `Set all ${String(toolCount)} ${providerLabel} ${toolCount === 1 ? "tool" : "tools"} to`

  return (
    <section className="overflow-hidden rounded-md border">
      <div
        className={cn(
          "bg-muted/30 flex items-center gap-3 pr-3 transition-colors",
          open ? "border-b" : ""
        )}
      >
        <button
          aria-expanded={open}
          className="hover:bg-muted/50 focus-visible:ring-ring/50 flex min-w-0 flex-1 items-center justify-between gap-3 px-3 py-2 text-left transition-colors outline-none hover:cursor-pointer focus-visible:ring-3 focus-visible:ring-inset"
          onClick={() => {
            onOpenChange(!open)
          }}
          type="button"
        >
          <div className="flex min-w-0 items-center gap-2">
            <ChevronRightIcon
              aria-hidden
              className={cn(
                "text-muted-foreground size-4 shrink-0 transition-transform",
                open ? "rotate-90" : ""
              )}
            />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{providerLabel}</p>
              <p className="text-muted-foreground text-xs">
                {toolCount} {toolCount === 1 ? "tool" : "tools"}
              </p>
            </div>
          </div>
          {activeCount > 0 ? <Badge variant="secondary">{activeCount} active</Badge> : null}
        </button>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                aria-label={`Set all ${providerLabel} tools`}
                size="sm"
                type="button"
                variant="outline"
              />
            }
          >
            Set All
            <ChevronDownIcon data-icon="inline-end" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-72">
            <DropdownMenuGroup>
              <DropdownMenuLabel>{scopeLabel}</DropdownMenuLabel>
              <BulkModeItem
                description="The agent can't use them."
                label="Off"
                onSelect={() => {
                  onModesChange(planBulkToolModes(group.tools, "off").modes)
                }}
              />
              {autoPlan.autoCount > 0 ? (
                <BulkModeItem
                  description={
                    autoPlan.approvalCount === 0
                      ? "They run without asking."
                      : `${String(autoPlan.autoCount)} run without asking · ${String(autoPlan.approvalCount)} that write still need approval.`
                  }
                  label="Auto where possible"
                  onSelect={() => {
                    onModesChange(autoPlan.modes)
                  }}
                />
              ) : null}
              <BulkModeItem
                description="A person confirms each use."
                label="Approval"
                onSelect={() => {
                  onModesChange(planBulkToolModes(group.tools, "approval").modes)
                }}
              />
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {open ? (
        <div className="divide-y">
          {group.tools.map((tool) => (
            <AgentToolPolicyRow
              key={tool.name}
              label={stripProviderPrefix(tool.label, providerLabel)}
              name={tool.name}
              description={tool.description}
              effect={tool.effect}
              mode={toolModes[tool.name] ?? "off"}
              modeOptions={toolModeOptions(tool)}
              onModeChange={(mode) => {
                onModeChange(tool.name, mode)
              }}
            />
          ))}
        </div>
      ) : null}
    </section>
  )
}

function BulkModeItem({
  description,
  label,
  onSelect,
}: {
  description: string
  label: string
  onSelect: () => void
}) {
  return (
    <DropdownMenuItem className="flex-col items-start gap-0.5" onClick={onSelect}>
      <span>{label}</span>
      <span className="text-muted-foreground text-xs">{description}</span>
    </DropdownMenuItem>
  )
}
