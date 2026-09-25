// apps/web/src/integrations/meta_ads/components/insights-filters.tsx

import { ListFieldInput } from "@/components/tool-ui/list-field-input"
import { Button } from "@/components/ui/button"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { ReportChoice } from "@/integrations/meta_ads/components/report-choice"
import type { InsightsFilter } from "@/integrations/meta_ads/lib/insights-approval"
import type { InsightsOptions } from "@/integrations/meta_ads/lib/insights-options"
import { titleCaseToken } from "@/lib/format"

export function InsightsFilters({
  id,
  value,
  fields,
  options,
  disabled,
  onChange,
}: {
  id: string
  value: InsightsFilter[]
  fields: string[]
  options: InsightsOptions
  disabled: boolean
  onChange: (value: InsightsFilter[]) => void
}) {
  const choices = [...new Set([...fields, ...options.filterFields])]
  const update = (index: number, patch: Partial<InsightsFilter>) => {
    onChange(value.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)))
  }
  return (
    <FieldGroup>
      {value.map((row, index) => {
        const rowId = `${id}-${String(index)}`
        const operator = row.operator
        const cell = row.value
        const isList = options.filterKinds[operator] === "list"
        const isNumber = options.filterKinds[operator] === "number" || typeof cell === "number"
        return (
          <FieldGroup key={rowId} className="rounded-md border p-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <ReportChoice
                id={`${rowId}-field`}
                label="Filter field"
                disabled={disabled}
                value={row.field}
                options={[...new Set([...choices, row.field])].map((field) => ({
                  value: field,
                  label: titleCaseToken(field, field),
                }))}
                onChange={(field) => {
                  update(index, { field })
                }}
              />
              <ReportChoice
                id={`${rowId}-operator`}
                label="Condition"
                disabled={disabled}
                value={operator}
                options={options.filterOperators.map((item) => ({
                  value: item,
                  label:
                    {
                      EQUAL: "Equals",
                      NOT_EQUAL: "Does not equal",
                      IN: "Is one of",
                      NOT_IN: "Is not one of",
                      CONTAIN: "Contains",
                      NOT_CONTAIN: "Does not contain",
                      GREATER_THAN: "Greater than",
                      LESS_THAN: "Less than",
                    }[item] ?? item,
                }))}
                onChange={(next) => {
                  const scalar = Array.isArray(cell) ? (cell[0] ?? "") : cell
                  const nextValue =
                    options.filterKinds[next] === "list"
                      ? Array.isArray(cell)
                        ? cell
                        : [String(scalar)]
                      : options.filterKinds[next] === "number"
                        ? Number.isFinite(Number(scalar))
                          ? Number(scalar)
                          : 0
                        : String(scalar)
                  update(index, { operator: next, value: nextValue })
                }}
              />
            </div>
            <Field>
              <FieldLabel htmlFor={`${rowId}-value`}>{isList ? "Values" : "Value"}</FieldLabel>
              {isList ? (
                <ListFieldInput
                  id={`${rowId}-value`}
                  ariaLabel="Filter values"
                  disabled={disabled}
                  value={Array.isArray(cell) ? cell.map(String) : []}
                  onChange={(values) => {
                    const original = new Map(
                      Array.isArray(cell) ? cell.map((item) => [String(item), item]) : []
                    )
                    update(index, { value: values.map((item) => original.get(item) ?? item) })
                  }}
                />
              ) : (
                <Input
                  id={`${rowId}-value`}
                  disabled={disabled}
                  type={isNumber ? "number" : "text"}
                  step={isNumber ? "any" : undefined}
                  value={typeof cell === "string" || typeof cell === "number" ? cell : ""}
                  onChange={(event) => {
                    update(index, {
                      value:
                        isNumber && event.currentTarget.value !== ""
                          ? Number(event.currentTarget.value)
                          : event.currentTarget.value,
                    })
                  }}
                />
              )}
            </Field>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={disabled}
              onClick={() => {
                onChange(value.filter((_, rowIndex) => rowIndex !== index))
              }}
            >
              Remove filter {String(index + 1)}
            </Button>
          </FieldGroup>
        )
      })}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="w-fit"
        disabled={disabled || value.length >= options.maxFilters}
        onClick={() => {
          onChange([
            ...value,
            { field: choices[0] ?? "", operator: options.filterOperators[0] ?? "", value: "" },
          ])
        }}
      >
        Add filter
      </Button>
    </FieldGroup>
  )
}
