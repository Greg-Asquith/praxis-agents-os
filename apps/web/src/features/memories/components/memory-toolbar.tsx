// apps/web/src/features/memories/components/memory-toolbar.tsx

import { useId } from "react"
import { ListFilterIcon, SearchIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
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
  MEMORY_ORIGIN_FILTER_LABELS,
  MEMORY_STATUS_LABELS,
} from "@/features/memories/components/memory-display"
import {
  DEFAULT_MEMORY_FILTERS,
  type MemoryFilters,
} from "@/features/memories/components/memory-filters"
import type { MemoryOrigin, MemoryStatus, MemoryType } from "@/features/memories/types"
import { isOneOf } from "@/lib/guards"

const ALL = "__all__"
const MEMORY_TYPES = ["fact", "preference", "episode", "outcome"] as const
const MEMORY_TYPE_SET: ReadonlySet<MemoryType> = new Set(MEMORY_TYPES)
const MEMORY_TYPE_LABELS: Record<MemoryType, string> = {
  fact: "Fact",
  preference: "Preference",
  episode: "Something That Happened",
  outcome: "Result",
}
const ORIGINS = ["learned", "agent", "person"] as const
const ORIGIN_SET: ReadonlySet<MemoryOrigin> = new Set(ORIGINS)
const STATUSES = ["active", "archived", "superseded"] as const
const STATUS_SET: ReadonlySet<MemoryStatus> = new Set(STATUSES)

export function MemoryToolbar({
  agents,
  filters,
  onFiltersChange,
  onSearchChange,
  search,
}: {
  agents: Agent[]
  filters: MemoryFilters
  onFiltersChange: (filters: MemoryFilters) => void
  onSearchChange: (search: string) => void
  search: string
}) {
  const moreFilterCount =
    (filters.memoryType ? 1 : 0) + (filters.status === DEFAULT_MEMORY_FILTERS.status ? 0 : 1)

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
      <div className="relative min-w-0 flex-1">
        <SearchIcon
          aria-hidden="true"
          className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
        />
        <Input
          aria-label="Search memories"
          autoComplete="off"
          className="pl-9"
          onChange={(event) => {
            onSearchChange(event.currentTarget.value)
          }}
          placeholder="Search memories…"
          type="search"
          value={search}
        />
      </div>
      <div className="flex flex-wrap gap-2">
        <FilterSelect
          allLabel="All Sources"
          label="Source"
          options={ORIGINS.map((origin) => [origin, MEMORY_ORIGIN_FILTER_LABELS[origin]])}
          value={filters.source}
          onChange={(value) => {
            onFiltersChange({
              ...filters,
              source: isOneOf(ORIGIN_SET, value) ? value : "",
            })
          }}
        />
        {filters.audience === "shared" ? (
          <FilterSelect
            allLabel="All Agents"
            label="Agent"
            options={agents.map((agent) => [agent.id, agent.name])}
            value={filters.agentId}
            onChange={(value) => {
              onFiltersChange({ ...filters, agentId: value })
            }}
          />
        ) : null}
        <Popover>
          <PopoverTrigger
            render={
              <Button type="button" variant="outline">
                <ListFilterIcon data-icon="inline-start" />
                More Filters
                {moreFilterCount > 0 ? <Badge variant="secondary">{moreFilterCount}</Badge> : null}
              </Button>
            }
          />
          <PopoverContent align="end" className="w-72 gap-3 p-3">
            <FieldGroup className="gap-3">
              <FilterSelect
                showLabel
                allLabel="All Types"
                label="Type"
                options={MEMORY_TYPES.map((type) => [type, MEMORY_TYPE_LABELS[type]])}
                value={filters.memoryType}
                onChange={(value) => {
                  onFiltersChange({
                    ...filters,
                    memoryType: isOneOf(MEMORY_TYPE_SET, value) ? value : "",
                  })
                }}
              />
              <FilterSelect
                showLabel
                label="Status"
                options={STATUSES.map((status) => [status, MEMORY_STATUS_LABELS[status]])}
                value={filters.status}
                onChange={(value) => {
                  onFiltersChange({
                    ...filters,
                    status: isOneOf(STATUS_SET, value) ? value : "active",
                  })
                }}
              />
            </FieldGroup>
          </PopoverContent>
        </Popover>
      </div>
    </div>
  )
}

function FilterSelect({
  allLabel,
  label,
  onChange,
  options,
  showLabel = false,
  value,
}: {
  allLabel?: string
  label: string
  onChange: (value: string) => void
  options: [string, string][]
  showLabel?: boolean
  value: string
}) {
  const triggerId = useId()
  const select = (
    <Select
      value={value || ALL}
      onValueChange={(nextValue) => {
        if (nextValue !== null) {
          onChange(nextValue === ALL ? "" : nextValue)
        }
      }}
    >
      <SelectTrigger
        aria-label={showLabel ? undefined : label}
        className={showLabel ? "w-full" : "min-w-40"}
        id={triggerId}
      >
        <SelectValue>
          {(selected: string) =>
            options.find(([optionValue]) => optionValue === selected)?.[1] ?? allLabel
          }
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {allLabel ? <SelectItem value={ALL}>{allLabel}</SelectItem> : null}
          {options.map(([optionValue, optionLabel]) => (
            <SelectItem key={optionValue} value={optionValue}>
              {optionLabel}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
  if (!showLabel) {
    return select
  }
  return (
    <Field>
      <FieldLabel htmlFor={triggerId}>{label}</FieldLabel>
      {select}
    </Field>
  )
}
