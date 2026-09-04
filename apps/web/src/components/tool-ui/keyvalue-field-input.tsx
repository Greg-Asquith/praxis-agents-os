// apps/web/src/components/tool-ui/keyvalue-field-input.tsx

import { PlusIcon, XIcon } from "lucide-react"

import type { EditedKeyValue, EditedScalar } from "@/components/tool-ui/edited-values"
import { nextKeyValueFieldName } from "@/components/tool-ui/keyvalue-field-values"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

export function KeyValueFieldInput({
  disabled,
  id,
  lockedEntries,
  maxEntries,
  onChange,
  value,
}: {
  disabled: boolean
  id: string
  lockedEntries: string[]
  maxEntries?: number
  onChange: (value: EditedKeyValue) => void
  value: EditedKeyValue
}) {
  const entries = Object.entries(value)

  function replaceKey(previousKey: string, nextKey: string) {
    const normalized = nextKey.trim()
    if (
      !normalized ||
      (normalized !== previousKey &&
        (Object.hasOwn(value, normalized) || lockedEntries.includes(normalized)))
    ) {
      return
    }
    onChange(
      Object.fromEntries(
        entries.map(([key, item]) => (key === previousKey ? [normalized, item] : [key, item]))
      )
    )
  }

  function updateValue(key: string, nextValue: EditedScalar) {
    onChange({ ...value, [key]: nextValue })
  }

  function addRow() {
    const key = nextKeyValueFieldName(value, lockedEntries)
    onChange({ ...value, [key]: "" })
  }

  return (
    <div className="border-input min-w-0 overflow-hidden rounded-lg border">
      <div className="bg-muted/30 text-muted-foreground grid grid-cols-[minmax(7rem,0.4fr)_minmax(0,1fr)_1.75rem] gap-2 border-b px-2.5 py-1.5 text-xs">
        <span>Field</span>
        <span>Value</span>
        <span className="sr-only">Actions</span>
      </div>
      <div className="divide-border divide-y">
        {entries.map(([key, item], index) => (
          <div
            className="grid min-w-0 grid-cols-[minmax(7rem,0.4fr)_minmax(0,1fr)_1.75rem] items-center gap-2 px-2.5 py-2"
            key={key}
          >
            <Input
              aria-label={`Field name ${String(index + 1)}`}
              className="h-7"
              defaultValue={key}
              disabled={disabled}
              onBlur={(event) => {
                replaceKey(key, event.currentTarget.value)
              }}
            />
            <ScalarInput
              disabled={disabled}
              id={`${id}-${String(index)}`}
              onChange={(nextValue) => {
                updateValue(key, nextValue)
              }}
              value={item}
            />
            <Button
              aria-label={`Remove ${key}`}
              disabled={disabled}
              onClick={() => {
                onChange(Object.fromEntries(entries.filter(([entryKey]) => entryKey !== key)))
              }}
              size="icon-xs"
              type="button"
              variant="ghost"
            >
              <XIcon />
            </Button>
          </div>
        ))}
        {lockedEntries.map((key) => (
          <div
            className="grid min-w-0 grid-cols-[minmax(7rem,0.4fr)_minmax(0,1fr)] gap-2 px-2.5 py-2"
            key={key}
          >
            <span className="truncate text-xs font-medium">{key}</span>
            <span className="text-muted-foreground text-xs">Complex value — read only</span>
          </div>
        ))}
      </div>
      <div className="border-border border-t px-2.5 py-1.5">
        <Button
          disabled={disabled || (maxEntries !== undefined && entries.length >= maxEntries)}
          onClick={addRow}
          size="sm"
          type="button"
          variant="ghost"
        >
          <PlusIcon />
          Add Field
        </Button>
      </div>
    </div>
  )
}

function ScalarInput({
  disabled,
  id,
  onChange,
  value,
}: {
  disabled: boolean
  id: string
  onChange: (value: EditedScalar) => void
  value: EditedScalar
}) {
  if (typeof value === "boolean") {
    return (
      <Select<boolean>
        disabled={disabled}
        onValueChange={(nextValue) => {
          if (nextValue !== null) {
            onChange(nextValue)
          }
        }}
        value={value}
      >
        <SelectTrigger className="h-7 w-full" id={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent align="start">
          <SelectGroup>
            <SelectItem label="Yes" value={true}>
              Yes
            </SelectItem>
            <SelectItem label="No" value={false}>
              No
            </SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>
    )
  }
  if (typeof value === "number") {
    return (
      <Input
        className="h-7"
        defaultValue={value}
        disabled={disabled}
        id={id}
        inputMode="decimal"
        onChange={(event) => {
          const nextValue = Number(event.currentTarget.value)
          if (event.currentTarget.value && Number.isFinite(nextValue)) {
            onChange(nextValue)
          }
        }}
        type="number"
      />
    )
  }
  return (
    <Input
      className="h-7"
      disabled={disabled}
      id={id}
      onChange={(event) => {
        onChange(event.currentTarget.value)
      }}
      value={value}
    />
  )
}
