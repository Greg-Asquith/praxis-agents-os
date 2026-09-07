// apps/web/src/components/tool-ui/records-field-input.tsx

import { Fragment, useRef, useState } from "react"
import { ChevronDownIcon, PlusIcon, XIcon } from "lucide-react"

import type { EditedRecordCell, EditedRecords } from "@/components/tool-ui/edited-values"
import { KeyValueFieldInput } from "@/components/tool-ui/keyvalue-field-input"
import { ListFieldInput } from "@/components/tool-ui/list-field-input"
import type { ToolFieldColumn } from "@/components/tool-ui/field-resolution"
import {
  addRecordRow,
  configuredRecordCellCount,
  keyedRecordRows,
  normalizeRecordNumericInput,
  recordRowsValidity,
  removeRecordRow,
  toggleRecordRowExpansion,
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
import { cn } from "@/lib/utils"

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
  const [expandedRows, setExpandedRows] = useState<Set<string>>(() => new Set())
  const rows = keyedRecordRows(value, rowKeys)
  const primaryColumns = columns.filter((column) => !column.secondary)
  const secondaryColumns = columns.filter((column) => column.secondary)
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
          <thead className="bg-card text-muted-foreground sticky top-0 z-10">
            <tr>
              {primaryColumns.map((column) => (
                <th
                  className="border-border border-b px-2.5 py-1.5 font-medium"
                  key={column.key}
                  scope="col"
                >
                  {column.label}
                  {column.required ? <span aria-hidden="true"> *</span> : null}
                </th>
              ))}
              <th className="border-border border-b px-1.5 py-1.5" scope="col">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ key, row, rowIndex }) => {
              const configuredFields = configuredRecordCellCount(row, secondaryColumns)
              const expanded = expandedRows.has(key)
              return (
                <Fragment key={key}>
                  <tr className="[&:not(:last-child)>td]:border-b">
                    {primaryColumns.map((column) => (
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
                    <td className="border-border px-1.5 py-2 text-right whitespace-nowrap">
                      {secondaryColumns.length > 0 ? (
                        <Button
                          aria-expanded={expanded}
                          aria-label={`${expanded ? "Hide" : "Show"} more fields in row ${String(rowIndex + 1)}${configuredFields > 0 ? `. ${String(configuredFields)} configured.` : "."}`}
                          disabled={disabled}
                          onClick={() => {
                            setExpandedRows((current) => toggleRecordRowExpansion(current, key))
                          }}
                          size="sm"
                          type="button"
                          variant="ghost"
                        >
                          {configuredFields > 0
                            ? `${String(configuredFields)} configured`
                            : "More fields"}
                          <ChevronDownIcon
                            data-icon="inline-end"
                            className={cn("transition-transform", expanded && "rotate-180")}
                          />
                        </Button>
                      ) : null}
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
                  {expanded ? (
                    <tr>
                      <td
                        className="border-border bg-muted/20 border-b p-3"
                        colSpan={primaryColumns.length + 1}
                      >
                        <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                          {secondaryColumns.map((column) => (
                            <div
                              className="grid min-w-0 gap-1 text-xs font-medium"
                              key={column.key}
                            >
                              <span>{column.label}</span>
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
                            </div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              )
            })}
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
  onChange: (value: EditedRecordCell) => void
  value: EditedRecordCell | undefined
}) {
  if (column.format === "list") {
    return <RecordListCell {...{ column, disabled, id, onChange, value }} />
  }
  if (column.format === "keyvalue") {
    return <RecordKeyValueCell {...{ column, disabled, id, onChange, value }} />
  }
  if (column.options.length > 0 && typeof value === "string") {
    return <RecordSelectCell {...{ column, disabled, id, label, onChange, value }} />
  }
  if (typeof value === "number") {
    return <RecordNumberCell {...{ column, disabled, id, label, onChange, value }} />
  }
  return <RecordTextCell {...{ column, disabled, id, label, onChange, value }} />
}

type RecordCellProps = {
  column: ToolFieldColumn
  disabled: boolean
  id: string
  onChange: (value: EditedRecordCell) => void
  value: EditedRecordCell | undefined
}

function RecordListCell({ column, disabled, id, onChange, value }: RecordCellProps) {
  return (
    <ListFieldInput
      disabled={disabled}
      id={id}
      onChange={onChange}
      {...(column.placeholder ? { placeholder: column.placeholder } : {})}
      value={Array.isArray(value) ? value : []}
    />
  )
}

function RecordKeyValueCell({ column, disabled, id, onChange, value }: RecordCellProps) {
  return (
    <KeyValueFieldInput
      disabled={disabled}
      id={id}
      lockedEntries={[]}
      {...(column.max_entries ? { maxEntries: column.max_entries } : {})}
      onChange={onChange}
      value={value && typeof value === "object" && !Array.isArray(value) ? value : {}}
    />
  )
}

function RecordSelectCell({
  column,
  disabled,
  id,
  label,
  onChange,
  value,
}: RecordCellProps & { label: string; value: string }) {
  return (
    <Select<string>
      disabled={disabled}
      onValueChange={(nextValue) => {
        if (nextValue !== null) onChange(nextValue)
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

function RecordNumberCell({
  column,
  disabled,
  id,
  label,
  onChange,
  value,
}: RecordCellProps & { label: string; value: number }) {
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

function RecordTextCell({
  column,
  disabled,
  id,
  label,
  onChange,
  value,
}: RecordCellProps & { label: string }) {
  const textValue = typeof value === "string" ? value : ""
  return (
    <Input
      aria-invalid={column.required && !textValue.trim()}
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
      value={textValue}
    />
  )
}
