// apps/web/src/features/agents/components/agent-tool-policy-row.tsx

import { Badge } from "@/components/ui/badge"
import { RUNTIME_TOOL_MODE_LABELS, type RuntimeToolMode } from "@/features/agents/runtime-tools"
import type { ToolCatalogEntry } from "@/features/tools/types"
import { cn } from "@/lib/utils"

export function AgentToolPolicyRow({
  description,
  effect,
  label,
  mode,
  modeOptions,
  muted = false,
  name,
  onModeChange,
}: {
  description: string
  effect?: ToolCatalogEntry["effect"]
  label: string
  mode: RuntimeToolMode
  modeOptions: RuntimeToolMode[]
  muted?: boolean
  name?: string
  onModeChange: (mode: RuntimeToolMode) => void
}) {
  return (
    <div
      className={cn(
        "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-3 py-3",
        mode !== "off" ? "bg-muted/20" : "",
        muted ? "bg-muted/30" : ""
      )}
    >
      <div className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <p className="truncate text-sm font-medium">{label}</p>
          {effect === "write" ? <Badge variant="outline">Writes</Badge> : null}
        </div>
        <p className="text-muted-foreground mt-1 truncate text-xs">{description}</p>
        {name ? (
          <p className="text-muted-foreground mt-1 truncate font-mono text-xs">{name}</p>
        ) : null}
      </div>
      <div
        aria-label={`${label} policy`}
        className="bg-background inline-flex shrink-0 items-center gap-0.5 rounded-md border p-0.5"
        role="radiogroup"
      >
        {modeOptions.map((value) => (
          <button
            aria-checked={mode === value}
            className={cn(
              "focus-visible:ring-ring/50 inline-flex h-7 items-center justify-center rounded-[4px] px-2.5 text-xs font-medium transition-colors hover:cursor-pointer focus-visible:ring-[3px] focus-visible:outline-1",
              mode === value
                ? "bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
            key={value}
            onClick={() => {
              onModeChange(value)
            }}
            role="radio"
            type="button"
          >
            {RUNTIME_TOOL_MODE_LABELS[value]}
          </button>
        ))}
      </div>
    </div>
  )
}
