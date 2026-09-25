// apps/web/src/integrations/meta_ads/components/report-choice.tsx

import { useState } from "react"

import {
  Combobox,
  ComboboxChip,
  ComboboxChipRemove,
  ComboboxChips,
  ComboboxCollection,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxInputGroup,
  ComboboxItem,
  ComboboxTrigger,
} from "@/components/ui/combobox"
import { Field, FieldLabel } from "@/components/ui/field"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { titleCaseToken } from "@/lib/format"

export function ReportChoice({
  id,
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  id: string
  label: string
  value: string
  options: { value: string; label: string }[]
  disabled: boolean
  onChange: (value: string) => void
}) {
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Select
        items={options}
        value={value}
        disabled={disabled}
        onValueChange={(next) => {
          if (next !== null) onChange(next)
        }}
      >
        <SelectTrigger id={id} className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            {options.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    </Field>
  )
}

export function ReportMultiChoice({
  id,
  label,
  value,
  options,
  disabled,
  onChange,
  allowCustom = false,
}: {
  id: string
  label: string
  value: string[]
  options: string[]
  disabled: boolean
  onChange: (value: string[]) => void
  allowCustom?: boolean
}) {
  const [search, setSearch] = useState("")
  const custom = search.trim()
  const items = [
    ...new Set([
      ...options,
      ...value,
      ...(allowCustom && /^[a-z0-9_]+$/.test(custom) ? [custom] : []),
    ]),
  ]
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Combobox<string, true>
        multiple
        items={items}
        value={value}
        disabled={disabled}
        onInputValueChange={setSearch}
        itemToStringLabel={(item) => titleCaseToken(item, item)}
        onValueChange={onChange}
      >
        <ComboboxInputGroup>
          <ComboboxChips>
            {value.map((item) => (
              <ComboboxChip key={item}>
                <span>{titleCaseToken(item, item)}</span>
                <ComboboxChipRemove aria-label={`Remove ${item} from ${label}`} />
              </ComboboxChip>
            ))}
            <ComboboxInput
              id={id}
              aria-label={`Search ${label}`}
              placeholder="Search and select…"
            />
          </ComboboxChips>
          <ComboboxTrigger aria-label={`Open ${label}`} />
        </ComboboxInputGroup>
        <ComboboxContent>
          <ComboboxEmpty>No matching options.</ComboboxEmpty>
          <ComboboxCollection>
            {(item: string) => (
              <ComboboxItem key={item} value={item}>
                {titleCaseToken(item, item)}
              </ComboboxItem>
            )}
          </ComboboxCollection>
        </ComboboxContent>
      </Combobox>
    </Field>
  )
}
