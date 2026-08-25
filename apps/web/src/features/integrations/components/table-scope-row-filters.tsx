// apps/web/src/features/integrations/components/table-scope-row-filters.tsx

import { useState } from "react"
import { FilterIcon, InfoIcon, PencilIcon, Trash2Icon, XIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldTitle,
} from "@/components/ui/field"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useResourceTablesQuery } from "@/features/integrations/api/list-resource-tables"
import {
  addTableScopeValues,
  type TableScopeDraft,
  tableScopeDraftError,
} from "@/features/integrations/components/table-scope-editor-model"
import type { TableScopeRule } from "@/features/integrations/types"
import { getErrorMessage } from "@/lib/api/errors"

export function TableScopeFilterChip({
  disabled,
  onEdit,
  onRemove,
  rule,
}: {
  disabled: boolean
  onEdit: () => void
  onRemove: () => void
  rule: TableScopeRule
}) {
  const values = rule.allowed_values
  return (
    <div className="bg-muted/25 flex min-w-0 items-center gap-2 rounded-md border px-2 py-1.5">
      <FilterIcon className="text-muted-foreground size-3 shrink-0" aria-hidden="true" />
      <p className="min-w-0 flex-1 truncate text-xs">
        <span className="font-medium">{rule.table_external_id}</span>
        <span className="text-muted-foreground"> · rows where </span>
        <span className="font-mono">{rule.column_name}</span>
        <span className="text-muted-foreground">
          {values.length === 1 ? " is " : " is one of "}
        </span>
        <span className="font-mono">{values.slice(0, 3).join(", ")}</span>
        {values.length > 3 ? (
          <span className="text-muted-foreground"> +{String(values.length - 3)} more</span>
        ) : null}
      </p>
      <div className="flex shrink-0 items-center gap-1">
        <Button
          aria-label={`Edit filter for ${rule.table_external_id}`}
          disabled={disabled}
          onClick={onEdit}
          size="icon-xs"
          type="button"
          variant="ghost"
        >
          <PencilIcon />
        </Button>
        <Button
          aria-label={`Remove filter for ${rule.table_external_id}`}
          disabled={disabled}
          onClick={onRemove}
          size="icon-xs"
          type="button"
          variant="ghost"
        >
          <Trash2Icon />
        </Button>
      </div>
    </div>
  )
}

export function TableScopeFilterFootnote({ id }: { id: string }) {
  return (
    <p
      className="text-muted-foreground flex items-start gap-1.5 px-2 text-xs leading-relaxed"
      id={id}
    >
      <InfoIcon className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
      Filters apply from the next query. While any filter exists, agents can query tables only — not
      views or wildcard table names. Remove a data source&apos;s filters before turning it off.
    </p>
  )
}

export function TableScopeRuleDialog({
  connectionId,
  draft: initialDraft,
  error,
  onAccept,
  onOpenChange,
  otherDrafts,
  pending,
}: {
  connectionId: string
  draft: TableScopeDraft
  error: string | null
  onAccept: (draft: TableScopeDraft) => void
  onOpenChange: (open: boolean) => void
  otherDrafts: TableScopeDraft[]
  pending: boolean
}) {
  const [draft, setDraft] = useState(initialDraft)
  const [showValidation, setShowValidation] = useState(false)
  const [valueInput, setValueInput] = useState("")
  const tablesQuery = useResourceTablesQuery({
    connectionId,
    enabled: true,
    resourceId: draft.resourceId,
  })
  const tables = tablesQuery.data?.pages.flatMap((page) => page.tables) ?? []
  const selectedTable = tables.find((table) => table.table_external_id === draft.tableExternalId)
  const candidate = {
    ...draft,
    allowedValues: addTableScopeValues(draft.allowedValues, valueInput),
  }
  const validationError = tableScopeDraftError(candidate, otherDrafts)
  const visibleValidationError = showValidation ? validationError : null
  const validationErrorId = `row-filter-error-${draft.id}`

  function selectTable(tableExternalId: string) {
    const table = tables.find((item) => item.table_external_id === tableExternalId)
    const column = table?.columns[0]
    setDraft((current) => ({
      ...current,
      columnName: column?.name ?? "",
      columnType: column?.column_type ?? "string",
      tableExternalId,
    }))
  }

  function selectColumn(columnName: string) {
    const column = selectedTable?.columns.find((item) => item.name === columnName)
    setDraft((current) => ({
      ...current,
      columnName,
      columnType: column?.column_type ?? current.columnType,
    }))
  }

  function addValues() {
    setDraft((current) => ({
      ...current,
      allowedValues: addTableScopeValues(current.allowedValues, valueInput),
    }))
    setValueInput("")
  }

  return (
    <Dialog onOpenChange={onOpenChange} open>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>
            {initialDraft.tableExternalId ? "Edit Row Filter" : "Add Row Filter"}
          </DialogTitle>
          <DialogDescription>
            Choose one table column and list the only values agents can read. Saving applies the
            filter from the next query.
          </DialogDescription>
        </DialogHeader>
        <FieldGroup className="gap-4">
          <Field>
            <FieldTitle>Data source</FieldTitle>
            <p className="text-muted-foreground truncate text-sm">{draft.resourceDisplayName}</p>
          </Field>
          <Field data-invalid={visibleValidationError ? true : undefined}>
            <FieldLabel htmlFor={`row-filter-table-${draft.id}`}>Table</FieldLabel>
            <Select
              onValueChange={(value) => {
                selectTable(value ?? "")
              }}
              value={draft.tableExternalId || null}
            >
              <SelectTrigger
                aria-describedby={visibleValidationError ? validationErrorId : undefined}
                aria-invalid={visibleValidationError ? true : undefined}
                className="w-full"
                disabled={tablesQuery.isPending || tablesQuery.isError}
                id={`row-filter-table-${draft.id}`}
              >
                <SelectValue>{(value) => selectDisplayValue(value, "Choose a table")}</SelectValue>
              </SelectTrigger>
              <SelectContent align="start">
                <SelectGroup>
                  <SelectItem disabled value={null}>
                    Choose a table
                  </SelectItem>
                  {draft.tableExternalId && !selectedTable ? (
                    <SelectItem value={draft.tableExternalId}>{draft.tableExternalId}</SelectItem>
                  ) : null}
                  {tables
                    .filter((table) => table.columns.length > 0)
                    .map((table) => (
                      <SelectItem key={table.table_external_id} value={table.table_external_id}>
                        {table.table_external_id}
                      </SelectItem>
                    ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
          {tablesQuery.isError ? (
            <Alert variant="destructive">
              <AlertTitle>Tables not loaded</AlertTitle>
              <AlertDescription className="flex flex-col items-start gap-2">
                <span>{getErrorMessage(tablesQuery.error)}</span>
                <Button
                  onClick={() => void tablesQuery.refetch()}
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  Try Again
                </Button>
              </AlertDescription>
            </Alert>
          ) : null}
          {tablesQuery.hasNextPage ? (
            <Button
              className="justify-self-start"
              disabled={tablesQuery.isFetchingNextPage}
              onClick={() => void tablesQuery.fetchNextPage()}
              size="sm"
              type="button"
              variant="ghost"
            >
              {tablesQuery.isFetchingNextPage ? "Loading" : "Load More Tables"}
            </Button>
          ) : null}
          <Field data-invalid={visibleValidationError ? true : undefined}>
            <FieldLabel htmlFor={`row-filter-column-${draft.id}`}>Filter column</FieldLabel>
            <Select
              onValueChange={(value) => {
                selectColumn(value ?? "")
              }}
              value={draft.columnName || null}
            >
              <SelectTrigger
                aria-describedby={visibleValidationError ? validationErrorId : undefined}
                aria-invalid={visibleValidationError ? true : undefined}
                className="w-full"
                disabled={!selectedTable}
                id={`row-filter-column-${draft.id}`}
              >
                <SelectValue>{(value) => selectDisplayValue(value, "Choose a column")}</SelectValue>
              </SelectTrigger>
              <SelectContent align="start">
                <SelectGroup>
                  {draft.columnName && !selectedTable ? (
                    <SelectItem value={draft.columnName}>{draft.columnName}</SelectItem>
                  ) : null}
                  {selectedTable?.columns.map((column) => (
                    <SelectItem key={column.name} value={column.name}>
                      {column.name} · {column.column_type === "integer" ? "Whole number" : "Text"}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
          <Field data-invalid={visibleValidationError ? true : undefined}>
            <FieldLabel htmlFor={`row-filter-value-${draft.id}`}>Allowed values</FieldLabel>
            <div className="flex gap-2">
              <Input
                aria-describedby={visibleValidationError ? validationErrorId : undefined}
                aria-invalid={visibleValidationError ? true : undefined}
                id={`row-filter-value-${draft.id}`}
                onChange={(event) => {
                  setValueInput(event.target.value)
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault()
                    addValues()
                  }
                }}
                placeholder={
                  draft.columnType === "integer" ? "For example, 12345" : "Enter a value"
                }
                value={valueInput}
              />
              <Button
                disabled={valueInput.length === 0}
                onClick={addValues}
                type="button"
                variant="outline"
              >
                Add
              </Button>
            </div>
            <FieldDescription className="text-xs">
              Add up to 200 values. Add each value separately.
            </FieldDescription>
            {draft.allowedValues.length > 0 ? (
              <div className="flex max-h-32 flex-wrap gap-1.5 overflow-y-auto rounded-lg border p-2">
                {draft.allowedValues.map((value) => (
                  <Badge className="gap-1 font-mono" key={value} variant="secondary">
                    <span className="max-w-64 truncate">{value}</span>
                    <button
                      aria-label={`Remove ${value}`}
                      className="hover:text-destructive cursor-pointer rounded-sm"
                      onClick={() => {
                        setDraft((current) => ({
                          ...current,
                          allowedValues: current.allowedValues.filter((item) => item !== value),
                        }))
                      }}
                      type="button"
                    >
                      <XIcon className="size-3" />
                    </button>
                  </Badge>
                ))}
              </div>
            ) : null}
          </Field>
          <FieldError className="text-xs" id={validationErrorId}>
            {visibleValidationError}
          </FieldError>
          {error ? (
            <Alert variant="destructive">
              <AlertTitle>Row filter not saved</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
          <p className="bg-muted/50 rounded-lg px-3 py-2 text-xs leading-relaxed">
            While any filter exists on this connection, agents can only query tables, not views.
          </p>
        </FieldGroup>
        <DialogFooter>
          <Button
            disabled={pending}
            onClick={() => {
              onOpenChange(false)
            }}
            type="button"
            variant="outline"
          >
            Cancel
          </Button>
          <Button
            disabled={pending}
            onClick={() => {
              if (validationError) {
                setShowValidation(true)
                return
              }
              onAccept(candidate)
            }}
            type="button"
          >
            {pending ? "Saving" : "Save Filter"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function selectDisplayValue(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback
}
