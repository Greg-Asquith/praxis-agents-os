// apps/web/src/features/agents/components/agent-tools-section.tsx

import { useCallback, useMemo, useState } from "react"
import { SearchIcon } from "lucide-react"

import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { AgentFormState } from "@/features/agents/components/agent-form-model"
import { AgentFormSection } from "@/features/agents/components/agent-form-section"
import {
  ALL_TOOL_PROVIDERS_VALUE,
  UNAVAILABLE_TOOL_PROVIDER_VALUE,
  filterTools,
  groupToolsByProvider,
  providerFilterOptions,
  unavailableModeOptions,
} from "@/features/agents/components/agent-tool-catalog-utils"
import { AgentToolPolicyRow } from "@/features/agents/components/agent-tool-policy-row"
import { AgentToolProviderGroup } from "@/features/agents/components/agent-tool-provider-group"
import type { RuntimeToolMode } from "@/features/agents/runtime-tools"
import type { ToolCatalogEntry } from "@/features/tools/types"

export function AgentToolsSection({
  onToolModeChange,
  state,
  toolCatalog,
}: {
  onToolModeChange: (toolName: string, mode: RuntimeToolMode) => void
  state: AgentFormState
  toolCatalog: ToolCatalogEntry[]
}) {
  const [search, setSearch] = useState("")
  const [providerFilter, setProviderFilter] = useState(ALL_TOOL_PROVIDERS_VALUE)
  const [expandedProviders, setExpandedProviders] = useState<Set<string>>(() => new Set())
  const normalizedSearch = search.trim().toLowerCase()
  const providerOptions = useMemo(() => providerFilterOptions(toolCatalog), [toolCatalog])
  const filteredCatalog = useMemo(
    () => filterTools(toolCatalog, providerFilter, normalizedSearch),
    [toolCatalog, providerFilter, normalizedSearch]
  )
  const toolGroups = useMemo(() => groupToolsByProvider(filteredCatalog), [filteredCatalog])
  const catalogToolNames = useMemo(
    () => new Set(toolCatalog.map((tool) => tool.name)),
    [toolCatalog]
  )
  const allUnavailableToolNames = useMemo(
    () =>
      Object.keys(state.toolModes).filter(
        (toolName) => !catalogToolNames.has(toolName) && state.toolModes[toolName] !== "off"
      ),
    [catalogToolNames, state.toolModes]
  )
  const unavailableToolNames = useMemo(
    () =>
      allUnavailableToolNames.filter(
        (toolName) =>
          (providerFilter === ALL_TOOL_PROVIDERS_VALUE ||
            providerFilter === UNAVAILABLE_TOOL_PROVIDER_VALUE) &&
          toolName.toLowerCase().includes(normalizedSearch)
      ),
    [allUnavailableToolNames, normalizedSearch, providerFilter]
  )
  const enabledCount = Object.values(state.toolModes).filter((mode) => mode !== "off").length
  const providerCount = providerOptions.length - 1
  const resultCount =
    filteredCatalog.length +
    (providerFilter === ALL_TOOL_PROVIDERS_VALUE ||
    providerFilter === UNAVAILABLE_TOOL_PROVIDER_VALUE
      ? unavailableToolNames.length
      : 0)
  const compactCatalog = toolCatalog.length <= 12
  const toggleProvider = useCallback((provider: string) => {
    setExpandedProviders((current) => {
      const next = new Set(current)
      if (next.has(provider)) {
        next.delete(provider)
      } else {
        next.add(provider)
      }
      return next
    })
  }, [])

  return (
    <AgentFormSection
      description="Choose which runtime tools are available and which ones require approval."
      eyebrow="Tools"
      title="Tools and approval policy"
    >
      <FieldGroup>
        <FieldSet>
          <FieldLegend>Runtime tools</FieldLegend>
          <div className="grid gap-4">
            <div className="bg-muted/30 grid gap-3 rounded-md border p-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
              <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2 text-sm">
                <span>
                  <span className="font-medium">{enabledCount}</span> enabled
                </span>
                <span className="text-muted-foreground">
                  {providerCount} {providerCount === 1 ? "provider" : "providers"}
                </span>
                <span className="text-muted-foreground">
                  {toolCatalog.length} {toolCatalog.length === 1 ? "tool" : "tools"}
                </span>
              </div>
              <span className="text-muted-foreground text-sm">{resultCount} shown</span>
            </div>
            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px] md:items-end">
              <Field>
                <FieldLabel htmlFor="agent-tool-search">Search tools</FieldLabel>
                <div className="relative">
                  <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
                  <Input
                    className="pl-9"
                    id="agent-tool-search"
                    onChange={(event) => {
                      setSearch(event.currentTarget.value)
                    }}
                    placeholder="Name, provider, or description"
                    type="search"
                    value={search}
                  />
                </div>
              </Field>
              <Field>
                <FieldLabel htmlFor="agent-tool-provider">Provider</FieldLabel>
                <Select
                  value={providerFilter}
                  onValueChange={(value) => {
                    setProviderFilter(value ?? ALL_TOOL_PROVIDERS_VALUE)
                  }}
                >
                  <SelectTrigger id="agent-tool-provider" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent align="end">
                    <SelectGroup>
                      <SelectLabel>Provider</SelectLabel>
                      {providerOptions.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                      {allUnavailableToolNames.length > 0 ? (
                        <SelectItem value={UNAVAILABLE_TOOL_PROVIDER_VALUE}>Unavailable</SelectItem>
                      ) : null}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </Field>
            </div>
            {toolGroups.map((group) => (
              <AgentToolProviderGroup
                key={group.provider}
                group={group}
                compactCatalog={compactCatalog}
                expanded={expandedProviders.has(group.provider)}
                forceOpen={normalizedSearch.length > 0}
                toolModes={state.toolModes}
                onModeChange={onToolModeChange}
                onToggle={() => {
                  toggleProvider(group.provider)
                }}
              />
            ))}
            {unavailableToolNames.length > 0 ? (
              <div className="overflow-hidden rounded-md border">
                <div className="bg-muted/30 border-b px-3 py-2">
                  <p className="text-sm font-medium">Unavailable</p>
                  <p className="text-muted-foreground text-xs">
                    {unavailableToolNames.length} configured{" "}
                    {unavailableToolNames.length === 1 ? "tool" : "tools"}
                  </p>
                </div>
                <div className="divide-y">
                  {unavailableToolNames.map((toolName) => (
                    <AgentToolPolicyRow
                      key={toolName}
                      label={toolName}
                      description="No longer available - set to Off to remove."
                      mode={state.toolModes[toolName] ?? "auto"}
                      modeOptions={unavailableModeOptions(state.toolModes[toolName])}
                      muted
                      onModeChange={(mode) => {
                        onToolModeChange(toolName, mode)
                      }}
                    />
                  ))}
                </div>
              </div>
            ) : null}
            {resultCount === 0 ? (
              <div className="rounded-md border border-dashed p-6 text-center">
                <p className="font-medium">No tools found</p>
                <p className="text-muted-foreground mt-1 text-sm">
                  Adjust the search or provider filter.
                </p>
              </div>
            ) : null}
          </div>
          <FieldDescription>
            Approval mode pauses a run and requires a human decision before the tool executes.
          </FieldDescription>
        </FieldSet>
      </FieldGroup>
    </AgentFormSection>
  )
}
