// apps/web/src/features/tools/components/tool-settings-panel.tsx

import { useMemo, useState } from "react"
import { ChevronRightIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useToolSettingsQuery } from "@/features/tools/api/list-tool-settings"
import { useUpdateToolSettingMutation } from "@/features/tools/api/update-tool-setting"
import type { ToolCatalogPolicy, ToolSetting } from "@/features/tools/types"
import { getErrorMessage } from "@/lib/api/errors"
import { titleCaseToken } from "@/lib/format"
import { cn } from "@/lib/utils"

type ToolSettingMode = "off" | ToolCatalogPolicy

type ToolGroup = { provider: string; label: string; tools: ToolSetting[] }

const MODE_LABELS: Record<ToolSettingMode, string> = {
  approval: "Ask first",
  auto: "Automatic",
  off: "Off",
}

export function ToolSettingsPanel() {
  const { data } = useToolSettingsQuery()
  const updateMutation = useUpdateToolSettingMutation()
  const [search, setSearch] = useState("")
  const [openProviders, setOpenProviders] = useState<ReadonlySet<string>>(() => new Set())
  const [error, setError] = useState<string | null>(null)
  const groups = useMemo(() => groupByProvider(filterTools(data.tools, search)), [data, search])
  const searching = search.trim().length > 0

  async function changeMode(tool: ToolSetting, mode: ToolSettingMode) {
    setError(null)
    try {
      if (mode === "off") {
        await updateMutation.mutateAsync({ toolName: tool.name, enabled: false })
        return
      }
      // Store no override when the choice matches the tool's own default.
      const policy = mode === tool.default_policy ? null : mode
      await updateMutation.mutateAsync({
        toolName: tool.name,
        ...(policy !== tool.policy && { policy }),
        ...(!tool.enabled && { enabled: true }),
      })
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
    }
  }

  function toggleProvider(provider: string) {
    setOpenProviders((current) => {
      const next = new Set(current)
      if (!next.delete(provider)) next.add(provider)
      return next
    })
  }

  return (
    <div className="flex flex-col gap-4 py-2">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <p className="text-muted-foreground max-w-2xl text-sm">
          Choose which tools agents can use and whether they ask first. Agents can override the
          approval choice for themselves.
        </p>
        <Input
          aria-label="Search tools"
          className="sm:w-64"
          onChange={(event) => {
            setSearch(event.currentTarget.value)
          }}
          placeholder="Search tools"
          value={search}
        />
      </div>
      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Tool setting not saved</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      {groups.length === 0 ? (
        <p className="text-muted-foreground text-sm">No tools match your search.</p>
      ) : (
        <div className="divide-border divide-y">
          {groups.map((group) => {
            // Searching expands every matching provider so results are visible.
            const open = searching || openProviders.has(group.provider)
            return (
              <section key={group.provider}>
                <button
                  aria-expanded={open}
                  className="hover:bg-muted/40 focus-visible:ring-ring/50 flex w-full items-center gap-2 rounded-md px-2 py-2.5 text-left outline-none hover:cursor-pointer focus-visible:ring-3"
                  onClick={() => {
                    toggleProvider(group.provider)
                  }}
                  type="button"
                >
                  <ChevronRightIcon
                    aria-hidden
                    className={cn(
                      "text-muted-foreground size-4 shrink-0 transition-transform",
                      open && "rotate-90"
                    )}
                  />
                  <span className="text-sm font-medium">{group.label}</span>
                  <span className="text-muted-foreground ml-auto text-xs">
                    {groupSummary(group.tools)}
                  </span>
                </button>
                {open ? (
                  <ul className="pb-2 pl-8">
                    {group.tools.map((tool) => (
                      <li className="flex items-center gap-4 py-1.5 pr-2" key={tool.name}>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm">
                            {stripProviderPrefix(tool.label, group.label)}
                          </p>
                          <p className="text-muted-foreground truncate text-xs">
                            {tool.description}
                          </p>
                        </div>
                        <Select
                          disabled={updateMutation.isPending}
                          onValueChange={(value) => {
                            if (isToolSettingMode(value)) void changeMode(tool, value)
                          }}
                          value={currentMode(tool)}
                        >
                          <SelectTrigger
                            aria-label={`${tool.label} setting`}
                            className="w-32 shrink-0"
                            size="sm"
                          >
                            <SelectValue>
                              {(value: ToolSettingMode) => MODE_LABELS[value]}
                            </SelectValue>
                          </SelectTrigger>
                          <SelectContent align="end">
                            <SelectGroup>
                              {modeOptions(tool).map((mode) => (
                                <SelectItem key={mode} value={mode}>
                                  {MODE_LABELS[mode]}
                                </SelectItem>
                              ))}
                            </SelectGroup>
                          </SelectContent>
                        </Select>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </section>
            )
          })}
        </div>
      )}
    </div>
  )
}

function currentMode(tool: ToolSetting): ToolSettingMode {
  return tool.enabled ? (tool.policy ?? tool.default_policy) : "off"
}

function modeOptions(tool: ToolSetting): ToolSettingMode[] {
  return [...tool.supported_policies.toSorted(), "off"]
}

function isToolSettingMode(value: unknown): value is ToolSettingMode {
  return value === "off" || value === "auto" || value === "approval"
}

function groupSummary(tools: ToolSetting[]) {
  const off = tools.filter((tool) => !tool.enabled).length
  const askFirst = tools.filter((tool) => currentMode(tool) === "approval").length
  const parts = [`${String(tools.length)} ${tools.length === 1 ? "tool" : "tools"}`]
  if (askFirst > 0) parts.push(`${String(askFirst)} ask first`)
  if (off > 0) parts.push(`${String(off)} off`)
  return parts.join(" · ")
}

function stripProviderPrefix(label: string, providerLabel: string) {
  if (!label.toLowerCase().startsWith(providerLabel.toLowerCase())) return label
  return label.slice(providerLabel.length).trim() || label
}

function filterTools(tools: ToolSetting[], search: string) {
  const normalized = search.trim().toLowerCase()
  if (!normalized) return tools
  return tools.filter((tool) =>
    [tool.label, tool.description, titleCaseToken(tool.provider, tool.provider)].some((value) =>
      value.toLowerCase().includes(normalized)
    )
  )
}

function groupByProvider(tools: ToolSetting[]): ToolGroup[] {
  const groups = new Map<string, ToolSetting[]>()
  for (const tool of tools) {
    groups.set(tool.provider, [...(groups.get(tool.provider) ?? []), tool])
  }
  return [...groups.entries()]
    .map(([provider, providerTools]) => ({
      provider,
      label: titleCaseToken(provider, provider),
      tools: providerTools.toSorted((left, right) => left.label.localeCompare(right.label)),
    }))
    .toSorted((left, right) => left.label.localeCompare(right.label))
}
