// apps/web/src/components/tool-ui/records-field-input.tsx

import { useRef, useState } from "react"
import { PlusIcon, XIcon } from "lucide-react"

import type { EditedRecords } from "@/components/tool-ui/edited-values"
import type { ToolFieldColumn } from "@/components/tool-ui/field-resolution"
import {
  addRecordRow,
  keyedRecordRows,
  removeRecordRow,
  updateRecordCell,
} from "@/components/tool-ui/records-field-values"
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
import { titleCaseToken } from "@/lib/format"

const MAX_RECORD_ROWS = 500

export function RecordsFieldInput({
  columns,
  disabled,
  id,
  labelId,
  onChange,
  value,
}: {
  columns: ToolFieldColumn[]
  disabled: boolean
  id: string
  labelId: string
  onChange: (value: EditedRecords) => void
  value: EditedRecords
}) {
  const nextRowKey = useRef(value.length)
  const [rowKeys, setRowKeys] = useState(() =>
    value.map((_, index) => `${id}-row-${String(index)}`)
  )
  const rows = keyedRecordRows(value, rowKeys)

  function addRow() {
    const key = `${id}-row-${String(nextRowKey.current)}`
    nextRowKey.current += 1
    setRowKeys((current) => [...current, key])
    onChange(addRecordRow(value, columns))
  }

  function removeRow(rowIndex: number) {
    setRowKeys((current) => current.filter((_, index) => index !== rowIndex))
    onChange(removeRecordRow(value, rowIndex))
  }

  return (
    <div
      aria-labelledby={labelId}
      className="border-input min-w-0 overflow-hidden rounded-lg border"
      role="group"
    >
      <div className="bg-muted/30 flex items-center justify-between gap-3 border-b px-2.5 py-1.5">
        <span className="text-muted-foreground text-xs font-medium">
          {String(value.length)} {value.length === 1 ? "row" : "rows"}
        </span>
        <Button
          disabled={disabled || value.length >= MAX_RECORD_ROWS}
          onClick={addRow}
          size="sm"
          type="button"
          variant="ghost"
        >
          <PlusIcon />
          Add Row
        </Button>
      </div>
      <div className="max-h-80 overflow-auto">
        <table className="w-full min-w-max border-separate border-spacing-0 text-left text-xs">
          <thead className="bg-muted/50 text-muted-foreground sticky top-0 z-10">
            <tr>
              {columns.map((column) => (
                <th
                  className="border-border/60 border-b px-2.5 py-1.5 font-medium"
                  key={column.key}
                >
                  {column.label}
                </th>
              ))}
              <th className="border-border/60 w-9 border-b px-1.5 py-1.5">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ key, row, rowIndex }) => (
              <tr className="[&:not(:last-child)>td]:border-b" key={key}>
                {columns.map((column) => (
                  <td className="border-border/60 min-w-40 px-2.5 py-2" key={column.key}>
                    <RecordCellInput
                      column={column}
                      disabled={disabled}
                      id={`${id}-${String(rowIndex)}-${column.key}`}
                      onChange={(nextValue) => {
                        onChange(updateRecordCell(value, rowIndex, column.key, nextValue))
                      }}
                      value={row[column.key]}
                    />
                  </td>
                ))}
                <td className="border-border/60 px-1.5 py-2 text-right">
                  <Button
                    aria-label={`Remove row ${String(rowIndex + 1)}`}
                    disabled={disabled}
                    onClick={() => {
                      removeRow(rowIndex)
                    }}
                    size="icon-xs"
                    type="button"
                    variant="ghost"
                  >
                    <XIcon />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function RecordCellInput({
  column,
  disabled,
  id,
  onChange,
  value,
}: {
  column: ToolFieldColumn
  disabled: boolean
  id: string
  onChange: (value: string | number) => void
  value: string | number | undefined
}) {
  if (column.options.length > 0 && typeof value === "string") {
    return (
      <Select<string>
        disabled={disabled}
        onValueChange={(nextValue) => {
          if (nextValue !== null) {
            onChange(nextValue)
          }
        }}
        value={value}
      >
        <SelectTrigger className="h-7 w-full" id={id}>
          <SelectValue placeholder={column.placeholder || undefined} />
        </SelectTrigger>
        <SelectContent align="start">
          <SelectGroup>
            {column.options.map((option) => (
              <SelectItem key={option} label={titleCaseToken(option, option)} value={option}>
                {titleCaseToken(option, option)}
              </SelectItem>
            ))}
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
      placeholder={column.placeholder || undefined}
      value={value ?? ""}
    />
  )
}
