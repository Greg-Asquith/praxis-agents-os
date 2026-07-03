// apps/web/src/features/audit/components/audit-filter-bar.tsx

import { RotateCcwIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
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
import {
  AUDIT_ACTIONS,
  AUDIT_RESOURCE_TYPES,
  AUDIT_STATUSES,
  SECURITY_EVENT_TYPES,
} from "@/features/audit/types"
import type { WorkspaceMembershipsListResponse } from "@/features/workspaces/types"
import { titleCaseToken } from "@/lib/format"

const ALL_FILTER_VALUE = "__all__"

export type AuditFilters = {
  action: string
  actorUserId: string
  occurredAfter: string
  occurredBefore: string
  resourceType: string
  status: string
}

export type SecurityFilters = {
  endpoint: string
  eventType: string
  ipAddress: string
  occurredAfter: string
  occurredBefore: string
  userEmail: string
}

type WorkspaceMembership = WorkspaceMembershipsListResponse["memberships"][number]

export function AuditFilterBar({
  filters,
  memberships,
  onFiltersChange,
}: {
  filters: AuditFilters
  memberships: WorkspaceMembership[]
  onFiltersChange: (filters: AuditFilters) => void
}) {
  function updateFilter(field: keyof AuditFilters, value: string) {
    onFiltersChange({ ...filters, [field]: value })
  }

  return (
    <div className="grid gap-3 lg:grid-cols-6">
      <FilterSelect
        label="Action"
        options={AUDIT_ACTIONS}
        placeholder="All actions"
        value={filters.action}
        onChange={(value) => {
          updateFilter("action", value)
        }}
      />
      <FilterSelect
        label="Resource"
        options={AUDIT_RESOURCE_TYPES}
        placeholder="All resources"
        value={filters.resourceType}
        onChange={(value) => {
          updateFilter("resourceType", value)
        }}
      />
      <FilterSelect
        label="Status"
        options={AUDIT_STATUSES}
        placeholder="All statuses"
        value={filters.status}
        onChange={(value) => {
          updateFilter("status", value)
        }}
      />
      <ActorSelect
        memberships={memberships}
        value={filters.actorUserId}
        onChange={(value) => {
          updateFilter("actorUserId", value)
        }}
      />
      <DateTimeInput
        label="From"
        value={filters.occurredAfter}
        onChange={(value) => {
          updateFilter("occurredAfter", value)
        }}
      />
      <DateTimeInput
        label="To"
        value={filters.occurredBefore}
        onChange={(value) => {
          updateFilter("occurredBefore", value)
        }}
      />
      <div className="lg:col-span-6">
        <Button
          disabled={isAuditFilterEmpty(filters)}
          onClick={() => {
            onFiltersChange({
              action: "",
              actorUserId: "",
              occurredAfter: "",
              occurredBefore: "",
              resourceType: "",
              status: "",
            })
          }}
          size="sm"
          type="button"
          variant="outline"
        >
          <RotateCcwIcon data-icon="inline-start" />
          Reset
        </Button>
      </div>
    </div>
  )
}

export function SecurityFilterBar({
  filters,
  onFiltersChange,
}: {
  filters: SecurityFilters
  onFiltersChange: (filters: SecurityFilters) => void
}) {
  function updateFilter(field: keyof SecurityFilters, value: string) {
    onFiltersChange({ ...filters, [field]: value })
  }

  return (
    <div className="grid gap-3 lg:grid-cols-6">
      <FilterSelect
        label="Event"
        options={SECURITY_EVENT_TYPES}
        placeholder="All events"
        value={filters.eventType}
        onChange={(value) => {
          updateFilter("eventType", value)
        }}
      />
      <TextInput
        label="User email"
        placeholder="person@example.com"
        value={filters.userEmail}
        onChange={(value) => {
          updateFilter("userEmail", value)
        }}
      />
      <TextInput
        label="IP address"
        placeholder="127.0.0.1"
        value={filters.ipAddress}
        onChange={(value) => {
          updateFilter("ipAddress", value)
        }}
      />
      <TextInput
        label="Endpoint"
        placeholder="/api/v1/auth/login"
        value={filters.endpoint}
        onChange={(value) => {
          updateFilter("endpoint", value)
        }}
      />
      <DateTimeInput
        label="From"
        value={filters.occurredAfter}
        onChange={(value) => {
          updateFilter("occurredAfter", value)
        }}
      />
      <DateTimeInput
        label="To"
        value={filters.occurredBefore}
        onChange={(value) => {
          updateFilter("occurredBefore", value)
        }}
      />
      <div className="lg:col-span-6">
        <Button
          disabled={isSecurityFilterEmpty(filters)}
          onClick={() => {
            onFiltersChange({
              endpoint: "",
              eventType: "",
              ipAddress: "",
              occurredAfter: "",
              occurredBefore: "",
              userEmail: "",
            })
          }}
          size="sm"
          type="button"
          variant="outline"
        >
          <RotateCcwIcon data-icon="inline-start" />
          Reset
        </Button>
      </div>
    </div>
  )
}

function FilterSelect({
  label,
  onChange,
  options,
  placeholder,
  value,
}: {
  label: string
  onChange: (value: string) => void
  options: readonly string[]
  placeholder: string
  value: string
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span className="text-sm leading-none font-medium">{label}</span>
      <Select
        value={value || ALL_FILTER_VALUE}
        onValueChange={(nextValue) => {
          onChange(!nextValue || nextValue === ALL_FILTER_VALUE ? "" : nextValue)
        }}
      >
        <SelectTrigger aria-label={label} className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent align="start">
          <SelectGroup>
            <SelectLabel>{label}</SelectLabel>
            <SelectItem value={ALL_FILTER_VALUE}>{placeholder}</SelectItem>
            {options.map((option) => (
              <SelectItem key={option} value={option}>
                {titleCaseToken(option, option)}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    </div>
  )
}

function ActorSelect({
  memberships,
  onChange,
  value,
}: {
  memberships: WorkspaceMembership[]
  onChange: (value: string) => void
  value: string
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span className="text-sm leading-none font-medium">Actor</span>
      <Select
        value={value || ALL_FILTER_VALUE}
        onValueChange={(nextValue) => {
          onChange(!nextValue || nextValue === ALL_FILTER_VALUE ? "" : nextValue)
        }}
      >
        <SelectTrigger aria-label="Actor" className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent align="start">
          <SelectGroup>
            <SelectLabel>Workspace actors</SelectLabel>
            <SelectItem value={ALL_FILTER_VALUE}>All actors</SelectItem>
            {memberships.map((membership) => (
              <SelectItem key={membership.id} value={membership.user_id}>
                {memberDisplayName(membership)}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    </div>
  )
}

function TextInput({
  label,
  onChange,
  placeholder,
  value,
}: {
  label: string
  onChange: (value: string) => void
  placeholder: string
  value: string
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span className="text-sm leading-none font-medium">{label}</span>
      <Input
        aria-label={label}
        placeholder={placeholder}
        value={value}
        onChange={(event) => {
          onChange(event.currentTarget.value)
        }}
      />
    </div>
  )
}

function DateTimeInput({
  label,
  onChange,
  value,
}: {
  label: string
  onChange: (value: string) => void
  value: string
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span className="text-sm leading-none font-medium">{label}</span>
      <Input
        aria-label={label}
        type="datetime-local"
        value={value}
        onChange={(event) => {
          onChange(event.currentTarget.value)
        }}
      />
    </div>
  )
}

function memberDisplayName(membership: WorkspaceMembership | undefined) {
  if (!membership) {
    return "Unknown actor"
  }

  return membership.user_display_name ?? membership.user_email ?? "Unknown actor"
}

function isAuditFilterEmpty(filters: AuditFilters) {
  return Object.values(filters).every((value) => value === "")
}

function isSecurityFilterEmpty(filters: SecurityFilters) {
  return Object.values(filters).every((value) => value === "")
}
