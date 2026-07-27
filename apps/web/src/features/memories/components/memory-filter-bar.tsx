// apps/web/src/features/memories/components/memory-filter-bar.tsx

import { useId } from "react"
import { RotateCcwIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { Agent } from "@/features/agents/types"
import {
  DEFAULT_MEMORY_FILTERS,
  type MemoryFilters,
} from "@/features/memories/components/memory-filters"
import type { MemoryKind, MemoryScope, MemoryStatus, MemoryType } from "@/features/memories/types"

const ALL = "__all__"

export function MemoryFilterBar({
  agents,
  filters,
  onFiltersChange,
}: {
  agents: Agent[]
  filters: MemoryFilters
  onFiltersChange: (filters: MemoryFilters) => void
}) {
  function updateFilter<Key extends keyof MemoryFilters>(key: Key, value: MemoryFilters[Key]) {
    onFiltersChange({ ...filters, [key]: value })
  }

  return (
    <FieldGroup className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <FilterSelect
        label="Scope"
        value={filters.scope}
        options={[
          ["agent", "Agent"],
          ["user", "Personal"],
          ["workspace", "Workspace"],
        ]}
        onChange={(value) => {
          updateFilter("scope", value as MemoryScope | "")
        }}
      />
      <FilterSelect
        label="Kind"
        value={filters.kind}
        options={[
          ["core", "Core"],
          ["note", "Note"],
        ]}
        onChange={(value) => {
          updateFilter("kind", value as MemoryKind | "")
        }}
      />
      <FilterSelect
        label="Type"
        value={filters.memoryType}
        options={[
          ["fact", "Fact"],
          ["preference", "Preference"],
          ["episode", "Episode"],
          ["outcome", "Outcome"],
        ]}
        onChange={(value) => {
          updateFilter("memoryType", value as MemoryType | "")
        }}
      />
      <FilterSelect
        label="Agent"
        value={filters.agentId}
        options={agents.map((agent) => [agent.id, agent.name])}
        onChange={(value) => {
          updateFilter("agentId", value)
        }}
      />
      <FilterSelect
        label="Status"
        showAll={false}
        value={filters.status}
        options={[
          ["active", "Active"],
          ["archived", "Archived"],
          ["superseded", "Superseded"],
        ]}
        onChange={(value) => {
          updateFilter("status", value as MemoryStatus)
        }}
      />
      <Button
        className="self-end sm:w-fit"
        disabled={sameFilters(filters, DEFAULT_MEMORY_FILTERS)}
        onClick={() => {
          onFiltersChange(DEFAULT_MEMORY_FILTERS)
        }}
        size="sm"
        type="button"
        variant="outline"
      >
        <RotateCcwIcon data-icon="inline-start" />
        Reset
      </Button>
    </FieldGroup>
  )
}

function FilterSelect({
  label,
  onChange,
  options,
  showAll = true,
  value,
}: {
  label: string
  onChange: (value: string) => void
  options: [string, string][]
  showAll?: boolean
  value: string
}) {
  const triggerId = useId()

  return (
    <Field className="min-w-0">
      <FieldLabel htmlFor={triggerId}>{label}</FieldLabel>
      <Select
        value={value || ALL}
        onValueChange={(nextValue) => {
          if (nextValue !== null) {
            onChange(nextValue === ALL ? "" : nextValue)
          }
        }}
      >
        <SelectTrigger className="w-full" id={triggerId}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            {showAll ? <SelectItem value={ALL}>All</SelectItem> : null}
            {options.map(([optionValue, optionLabel]) => (
              <SelectItem key={optionValue} value={optionValue}>
                {optionLabel}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    </Field>
  )
}

function sameFilters(left: MemoryFilters, right: MemoryFilters) {
  return (
    left.scope === right.scope &&
    left.kind === right.kind &&
    left.memoryType === right.memoryType &&
    left.agentId === right.agentId &&
    left.status === right.status
  )
}
