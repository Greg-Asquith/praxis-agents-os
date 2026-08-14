// apps/web/src/features/agents/components/agent-tools-section.tsx

import { useMemo, useState } from "react"
import { InfoIcon, SearchIcon } from "lucide-react"

import { FormSection } from "@/components/forms/form-section"
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
  FieldTitle,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverHeader, PopoverTrigger } from "@/components/ui/popover"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import type { AgentFormState } from "@/features/agents/components/agent-form-model"
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
  onCodeModeEnabledChange,
  onToolModeChange,
  state,
  toolCatalog,
}: {
  onCodeModeEnabledChange: (enabled: boolean) => void
  onToolModeChange: (toolName: string, mode: RuntimeToolMode) => void
  state: AgentFormState
  toolCatalog: ToolCatalogEntry[]
}) {
  const [search, setSearch] = useState("")
  const [providerFilter, setProviderFilter] = useState(ALL_TOOL_PROVIDERS_VALUE)
  const [providerOpenOverrides, setProviderOpenOverrides] = useState<Record<string, boolean>>({})
  const configurableToolCatalog = useMemo(
    () => toolCatalog.filter((tool) => tool.name !== "run_workflow"),
    [toolCatalog]
  )
  const normalizedSearch = search.trim().toLowerCase()
  const providerOptions = useMemo(
    () => providerFilterOptions(configurableToolCatalog),
    [configurableToolCatalog]
  )
  const filteredCatalog = useMemo(
    () => filterTools(configurableToolCatalog, providerFilter, normalizedSearch),
    [configurableToolCatalog, providerFilter, normalizedSearch]
  )
  const toolGroups = useMemo(() => groupToolsByProvider(filteredCatalog), [filteredCatalog])
  const catalogToolNames = useMemo(
    () => new Set(configurableToolCatalog.map((tool) => tool.name)),
    [configurableToolCatalog]
  )
  const allUnavailableToolNames = useMemo(
    () =>
      Object.keys(state.toolModes).filter(
        (toolName) =>
          toolName !== "run_workflow" &&
          !catalogToolNames.has(toolName) &&
          state.toolModes[toolName] !== "off"
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
  const approvalCount = Object.values(state.toolModes).filter((mode) => mode === "approval").length
  const resultCount =
    filteredCatalog.length +
    (providerFilter === ALL_TOOL_PROVIDERS_VALUE ||
    providerFilter === UNAVAILABLE_TOOL_PROVIDER_VALUE
      ? unavailableToolNames.length
      : 0)
  const totalToolCount = configurableToolCatalog.length + allUnavailableToolNames.length
  const hasActiveFilter = normalizedSearch.length > 0 || providerFilter !== ALL_TOOL_PROVIDERS_VALUE
  return (
    <FormSection
      description="Tools let an agent read information or take actions in connected systems. Approval means a person confirms each use before it runs. You can change this later."
      eyebrow="Tools"
      title="Tools and approval policy"
    >
      <FieldGroup>
        <Field orientation="horizontal">
          <FieldContent>
            <div className="flex items-center gap-1.5">
              <FieldTitle>Let this agent combine tools in one workflow</FieldTitle>
              <Popover>
                <PopoverTrigger
                  render={
                    <Button
                      aria-label="About combining tools"
                      size="icon-xs"
                      type="button"
                      variant="ghost"
                    />
                  }
                >
                  <InfoIcon />
                </PopoverTrigger>
                <CodeModeInfoContent />
              </Popover>
            </div>
            <FieldDescription>
              The agent can work through several enabled tools as one clear workflow.
            </FieldDescription>
          </FieldContent>
          <Switch
            aria-label="Let this agent combine tools in one workflow"
            checked={state.codeModeEnabled}
            onCheckedChange={onCodeModeEnabledChange}
          />
        </Field>
        <FieldSet>
          <FieldLegend>Choose tools</FieldLegend>
          <p className="text-muted-foreground text-sm">
            {enabledCount === 0 ? (
              "No tools enabled yet. Turn on only what this agent needs."
            ) : (
              <>
                <span className="text-foreground font-medium">
                  {enabledCount} {enabledCount === 1 ? "tool" : "tools"} enabled
                </span>
                <span aria-hidden="true"> · </span>
                {approvalCount === 0
                  ? "No approvals required"
                  : `${String(approvalCount)} ${approvalCount === 1 ? "requires" : "require"} approval`}
              </>
            )}
          </p>
          <div className="grid gap-4">
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
            {hasActiveFilter ? (
              <p aria-live="polite" className="text-muted-foreground -mt-1 text-right text-xs">
                Showing {resultCount} of {totalToolCount} {totalToolCount === 1 ? "tool" : "tools"}
              </p>
            ) : null}
            {toolGroups.map((group) => (
              <AgentToolProviderGroup
                key={group.provider}
                group={group}
                forceOpen={normalizedSearch.length > 0}
                openOverride={providerOpenOverrides[group.provider]}
                toolModes={state.toolModes}
                onModeChange={onToolModeChange}
                onOpenChange={(open) => {
                  setProviderOpenOverrides((current) => ({
                    ...current,
                    [group.provider]: open,
                  }))
                }}
              />
            ))}
            {unavailableToolNames.length > 0 ? (
              <div className="overflow-hidden rounded-md border">
                <div className="bg-muted/30 border-b px-3 py-2">
                  <p className="text-sm font-medium">Unavailable</p>
                  <p className="text-muted-foreground text-xs">
                    {unavailableToolNames.length} selected{" "}
                    {unavailableToolNames.length === 1
                      ? "tool is currently unavailable"
                      : "tools are currently unavailable"}
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
              <div className="bg-muted/30 rounded-lg p-6 text-center">
                <p className="font-medium">No tools found</p>
                <p className="text-muted-foreground mt-1 text-sm">
                  Adjust the search or provider filter.
                </p>
              </div>
            ) : null}
          </div>
        </FieldSet>
      </FieldGroup>
    </FormSection>
  )
}

function CodeModeInfoContent() {
  return (
    <PopoverContent align="start" className="w-[min(24rem,calc(100vw-2rem))]">
      <CodeModeInfoBody />
    </PopoverContent>
  )
}

export function CodeModeInfoBody() {
  return (
    <>
      <PopoverHeader>
        <h3 className="font-medium">Combine tools in one workflow</h3>
        <p className="text-muted-foreground">
          Lets the agent combine several tools in one workflow, working through data without
          back-and-forth.
        </p>
      </PopoverHeader>
      <p className="text-muted-foreground text-sm">
        Use it for agents that run reports, reconcile, or act on many items at once — for example,
        run an ads report, work out the weakest campaigns, and pause them. Leave it off for simple
        chat or single-action agents.
      </p>
    </>
  )
}
