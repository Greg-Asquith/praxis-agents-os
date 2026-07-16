// apps/web/src/features/agents/components/agent-tool-provider-group.tsx

import { ChevronRightIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import type { AgentFormState } from "@/features/agents/components/agent-form-model"
import {
  stripProviderPrefix,
  type ToolGroup,
} from "@/features/agents/components/agent-tool-catalog-utils"
import { AgentToolPolicyRow } from "@/features/agents/components/agent-tool-policy-row"
import { toolModeOptions, type RuntimeToolMode } from "@/features/agents/runtime-tools"
import { titleCaseToken } from "@/lib/format"
import { cn } from "@/lib/utils"

export function AgentToolProviderGroup({
  compactCatalog,
  forceOpen,
  group,
  onModeChange,
  onOpenChange,
  openOverride,
  toolModes,
}: {
  compactCatalog: boolean
  forceOpen: boolean
  group: ToolGroup
  onModeChange: (toolName: string, mode: RuntimeToolMode) => void
  onOpenChange: (open: boolean) => void
  openOverride: boolean | undefined
  toolModes: AgentFormState["toolModes"]
}) {
  const activeCount = group.tools.filter((tool) => (toolModes[tool.name] ?? "off") !== "off").length
  const open = openOverride ?? (forceOpen || activeCount > 0 || compactCatalog)
  const providerLabel = titleCaseToken(group.provider, group.provider)

  return (
    <section className="overflow-hidden rounded-md border">
      <button
        aria-expanded={open}
        className={cn(
          "bg-muted/30 hover:bg-muted/50 flex w-full items-center justify-between gap-3 px-3 py-2 text-left transition-colors hover:cursor-pointer",
          open ? "border-b" : ""
        )}
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
              {group.tools.length} {group.tools.length === 1 ? "tool" : "tools"}
            </p>
          </div>
        </div>
        {activeCount > 0 ? <Badge variant="secondary">{activeCount} active</Badge> : null}
      </button>
      {open ? (
        <div className="max-h-96 divide-y overflow-y-auto">
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
