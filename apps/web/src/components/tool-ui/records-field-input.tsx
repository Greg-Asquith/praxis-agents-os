// apps/web/src/components/tool-ui/records-field-input.tsx

import { useRef, useState } from "react"
import { PlusIcon, XIcon } from "lucide-react"

import type { EditedRecords } from "@/components/tool-ui/edited-values"
import type { ToolFieldColumn } from "@/components/tool-ui/field-resolution"
import {
  addRecordRow,
  keyedRecordRows,
  normalizeRecordNumericInput,
  recordRowsValidity,
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
  minRows,
  onChange,
  value,
}: {
  columns: ToolFieldColumn[]
  disabled: boolean
  id: string
  labelId: string
  minRows: number
  onChange: (value: EditedRecords) => void
  value: EditedRecords
}) {
  const nextRowKey = useRef(value.length)
  const [rowKeys, setRowKeys] = useState(() =>
    value.map((_, index) => `${id}-row-${String(index)}`)
  )
  const rows = keyedRecordRows(value, rowKeys)
  const validation = recordRowsValidity(value, columns, minRows)
  const error = validation.isRecords ? validation.error : null

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
      aria-describedby={error ? `${id}-error` : undefined}
      aria-labelledby={labelId}
      className="min-w-0 overflow-hidden"
      role="group"
    >
      <div className="border-border/70 flex items-center justify-between gap-3 border-b py-1">
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
          <thead className="bg-muted/30 text-muted-foreground sticky top-0 z-10">
            <tr>
              {columns.map((column) => (
                <th
                  className="border-border border-b px-2.5 py-1.5 font-medium"
                  key={column.key}
                  scope="col"
                >
                  {column.label}
                  {column.required ? <span aria-hidden="true"> *</span> : null}
                </th>
              ))}
              <th className="border-border w-9 border-b px-1.5 py-1.5" scope="col">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ key, row, rowIndex }) => (
              <tr className="[&:not(:last-child)>td]:border-b" key={key}>
                {columns.map((column) => (
                  <td className="border-border min-w-40 px-2.5 py-2" key={column.key}>
                    <RecordCellInput
                      column={column}
                      disabled={disabled}
                      id={`${id}-${String(rowIndex)}-${column.key}`}
                      label={`${column.label}, row ${String(rowIndex + 1)}`}
                      onChange={(nextValue) => {
                        onChange(updateRecordCell(value, rowIndex, column.key, nextValue))
                      }}
                      value={row[column.key]}
                    />
                  </td>
                ))}
                <td className="border-border px-1.5 py-2 text-right">
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
      {error ? (
        <p aria-live="polite" className="text-destructive mt-1.5 text-xs" id={`${id}-error`}>
          {error}
        </p>
      ) : null}
    </div>
  )
}

function RecordCellInput({
  column,
  disabled,
  id,
  label,
  onChange,
  value,
}: {
  column: ToolFieldColumn
  disabled: boolean
  id: string
  label: string
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
        <SelectTrigger
          aria-invalid={column.required && !value.trim()}
          aria-label={label}
          aria-required={column.required}
          className="h-7 w-full"
          id={id}
        >
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
        aria-label={label}
        aria-required={column.required}
        autoComplete="off"
        className="h-7"
        disabled={disabled}
        id={id}
        inputMode="decimal"
        name={id}
        onChange={(event) => {
          const nextValue = normalizeRecordNumericInput(event.currentTarget.value)
          if (nextValue === null) {
            event.currentTarget.value = String(value)
            return
          }
          onChange(nextValue)
        }}
        type="number"
        value={value}
      />
    )
  }
  return (
    <Input
      aria-invalid={column.required && !value?.trim()}
      aria-label={label}
      aria-required={column.required}
      autoComplete="off"
      className="h-7"
      disabled={disabled}
      id={id}
      name={id}
      onChange={(event) => {
        onChange(event.currentTarget.value)
      }}
      placeholder={column.placeholder || undefined}
      value={value ?? ""}
    />
  )
}
