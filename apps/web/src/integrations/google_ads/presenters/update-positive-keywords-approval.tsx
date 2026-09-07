// apps/web/src/integrations/google_ads/presenters/update-positive-keywords-approval.tsx

import { Fragment, useState } from "react"
import { ArrowRightIcon, ChevronDownIcon } from "lucide-react"

import type { EditedRecordCell, EditedRecords } from "@/components/tool-ui/edited-values"
import { KeyValueFieldInput } from "@/components/tool-ui/keyvalue-field-input"
import { ListFieldInput } from "@/components/tool-ui/list-field-input"
import { Button } from "@/components/ui/button"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type {
  PositiveKeywordStatus,
  PositiveKeywordReference,
} from "@/integrations/google_ads/lib/positive-keywords"
import {
  formatPositiveKeywordValue,
  mutableStateFromReference,
  POSITIVE_KEYWORD_PATCH_FIELDS,
  POSITIVE_KEYWORD_PATCH_FIELDS_BY_KEY,
  replacePositiveKeywordPatch,
  type KeywordPatch,
  type MutableKeywordState,
  type PatchField,
  type PositiveKeywordUpdateArgs,
} from "@/integrations/google_ads/lib/positive-keyword-update"
import { titleCaseToken } from "@/lib/format"

import { isRecord } from "@/lib/guards"
import { cn } from "@/lib/utils"

const APPROVAL_PAGE_SIZE = 25

export function UpdatePositiveKeywordsApproval({
  args,
  disabled,
  onChange,
}: {
  args: PositiveKeywordUpdateArgs
  disabled: boolean
  onChange: (patches: EditedRecords) => void
}) {
  const [pageIndex, setPageIndex] = useState(0)
  const [expandedRows, setExpandedRows] = useState<Set<string>>(
    () =>
      new Set(
        args.keywords
          .filter((_keyword, index) => hasAdvancedPatchField(args.patches[index] ?? {}))
          .map((keyword) => keyword.identity)
      )
  )
  const pageCount = Math.ceil(args.keywords.length / APPROVAL_PAGE_SIZE)
  const safePageIndex = Math.min(pageIndex, Math.max(pageCount - 1, 0))
  const start = safePageIndex * APPROVAL_PAGE_SIZE
  const visibleKeywords = args.keywords.slice(start, start + APPROVAL_PAGE_SIZE)

  function updatePatch(rowIndex: number, patch: KeywordPatch) {
    onChange(replacePositiveKeywordPatch(args.patches, rowIndex, patch).map(editablePatch))
  }

  return (
    <section aria-label="Proposed keyword changes" className="flex flex-col gap-2">
      <ApprovalPagination
        disabled={disabled}
        itemCount={args.keywords.length}
        onPageChange={setPageIndex}
        pageCount={pageCount}
        pageIndex={safePageIndex}
      />
      {visibleKeywords.map((keyword, visibleIndex) => {
        const index = start + visibleIndex
        const patch = args.patches[index]
        if (!patch) return null
        const account = args.accounts.get(keyword.customerId)
        const expanded = expandedRows.has(keyword.identity)
        return (
          <Fragment key={keyword.identity}>
            {visibleIndex === 0 ||
            visibleKeywords[visibleIndex - 1]?.customerId !== keyword.customerId ||
            visibleKeywords[visibleIndex - 1]?.scopeLabel !== keyword.scopeLabel ? (
              <div className="border-border mt-1 border-b pb-2">
                <p className="text-muted-foreground text-xs wrap-anywhere">
                  {account?.label ?? "Google Ads account"} ·{" "}
                  {account?.currencyCode ?? "Currency unavailable"}
                </p>
                <p className="mt-1 text-xs wrap-anywhere">{keyword.scopeLabel}</p>
                <div
                  aria-hidden="true"
                  className="text-muted-foreground mt-3 hidden gap-4 text-xs sm:grid sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)_8rem]"
                >
                  <span>Keyword</span>
                  <span>Status</span>
                  <span>CPC bid ({account?.currencyCode})</span>
                  <span />
                </div>
              </div>
            ) : null}
            <KeywordPatchEditor
              account={account}
              disabled={disabled}
              expanded={expanded}
              keyword={keyword}
              onChange={(nextPatch) => {
                updatePatch(index, nextPatch)
              }}
              onExpandedChange={() => {
                setExpandedRows((current) => toggleExpanded(current, keyword.identity))
              }}
              patch={patch}
            />
          </Fragment>
        )
      })}
    </section>
  )
}

function ApprovalPagination({
  disabled,
  itemCount,
  onPageChange,
  pageCount,
  pageIndex,
}: {
  disabled: boolean
  itemCount: number
  onPageChange: (page: number) => void
  pageCount: number
  pageIndex: number
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <p className="text-muted-foreground text-xs">
        {String(itemCount)} {itemCount === 1 ? "keyword" : "keywords"}. Edit the values to change.
      </p>
      {pageCount > 1 ? (
        <div className="flex shrink-0 items-center gap-1">
          <Button
            disabled={disabled || pageIndex === 0}
            onClick={() => {
              onPageChange(Math.max(0, pageIndex - 1))
            }}
            size="sm"
            type="button"
            variant="ghost"
          >
            Previous
          </Button>
          <span className="text-muted-foreground text-xs">
            {String(pageIndex + 1)} of {String(pageCount)}
          </span>
          <Button
            disabled={disabled || pageIndex >= pageCount - 1}
            onClick={() => {
              onPageChange(Math.min(pageCount - 1, pageIndex + 1))
            }}
            size="sm"
            type="button"
            variant="ghost"
          >
            Next
          </Button>
        </div>
      ) : null}
    </div>
  )
}

function KeywordPatchEditor({
  account,
  disabled,
  expanded,
  keyword,
  onChange,
  onExpandedChange,
  patch,
}: {
  account: { currencyCode: string; label: string } | undefined
  disabled: boolean
  expanded: boolean
  keyword: PositiveKeywordReference
  onChange: (patch: KeywordPatch) => void
  onExpandedChange: () => void
  patch: KeywordPatch
}) {
  const before = mutableStateFromReference(keyword)
  return (
    <article
      aria-label={`${keyword.text}, ${keyword.matchType}, ${keyword.scopeLabel}, account ${keyword.customerId}`}
      className="border-border min-w-0 border-b py-2 last:border-b-0"
    >
      <div className="grid items-start gap-3 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)_8rem] sm:gap-4">
        <div className="min-w-0 sm:pt-1">
          <p className="text-sm font-medium wrap-anywhere">{keyword.text}</p>
          <p className="text-muted-foreground mt-0.5 text-xs">
            {titleCaseToken(keyword.matchType.toLowerCase(), keyword.matchType)}
          </p>
        </div>
        {POSITIVE_KEYWORD_PATCH_FIELDS.filter((field) => !field.advanced).map((field) => (
          <PatchFieldEditor
            before={before}
            compact
            currencyCode={account?.currencyCode ?? ""}
            disabled={disabled}
            field={field.key}
            key={field.key}
            keyword={keyword}
            onChange={onChange}
            patch={patch}
          />
        ))}
        <Button
          aria-expanded={expanded}
          aria-label={`${expanded ? "Less fields" : "More fields"} for ${keyword.text}, ${keyword.matchType}, account ${keyword.customerId}`}
          className="justify-self-start sm:justify-self-end"
          disabled={disabled}
          onClick={onExpandedChange}
          size="sm"
          type="button"
          variant="ghost"
        >
          {expanded ? "Less fields" : "More fields"}
          <ChevronDownIcon
            className={cn("transition-transform", expanded && "rotate-180")}
            data-icon="inline-end"
          />
        </Button>
      </div>
      {expanded ? (
        <FieldGroup className="bg-muted/25 mt-3 grid gap-4 rounded-md p-3 sm:grid-cols-2">
          {POSITIVE_KEYWORD_PATCH_FIELDS.filter((field) => field.advanced).map((field) => (
            <PatchFieldEditor
              before={before}
              currencyCode={account?.currencyCode ?? ""}
              disabled={disabled}
              field={field.key}
              key={field.key}
              keyword={keyword}
              onChange={onChange}
              patch={patch}
            />
          ))}
        </FieldGroup>
      ) : null}
    </article>
  )
}

function PatchFieldEditor({
  before,
  compact = false,
  currencyCode,
  disabled,
  field,
  keyword,
  onChange,
  patch,
}: {
  before: MutableKeywordState
  compact?: boolean
  currencyCode: string
  disabled: boolean
  field: PatchField
  keyword: PositiveKeywordReference
  onChange: (patch: KeywordPatch) => void
  patch: KeywordPatch
}) {
  const included = Object.hasOwn(patch, field)
  const specification = POSITIVE_KEYWORD_PATCH_FIELDS_BY_KEY.get(field)
  if (!specification) return null
  const inputId = `${keyword.identity}-${field}`
  const value = included ? (patch[field] ?? null) : before[field]
  const changed = included && !sameFieldValue(field, before[field], value)
  const context = `${keyword.text}, ${titleCaseToken(keyword.matchType.toLowerCase(), keyword.matchType)}, in ${keyword.scopeLabel}, account ${keyword.customerId}`
  const label = `${specification.label} for ${context}`
  return (
    <Field className="min-w-0 gap-1.5" data-disabled={disabled || undefined}>
      <FieldLabel className={cn("min-w-0", compact && "sm:sr-only")} htmlFor={inputId}>
        {specification.label}
        {field === "cpc_bid" && currencyCode ? ` (${currencyCode})` : ""}
      </FieldLabel>
      <div className={cn("min-w-0 rounded-md", changed && "bg-warning/5 ring-warning/40 ring-1")}>
        <PatchValueInput
          disabled={disabled}
          field={field}
          id={inputId}
          label={label}
          onChange={(nextValue) => {
            onChange(withPatchField(patch, field, nextValue))
          }}
          value={value}
        />
      </div>
      {changed ? (
        <p className="text-warning-foreground flex min-w-0 flex-wrap items-baseline gap-x-1 text-xs">
          <span className="sr-only">Changed. </span>
          <span className="wrap-anywhere">
            <span className="sr-only">Before: </span>
            {formatPositiveKeywordValue(field, before[field], currencyCode)}
          </span>
          <ArrowRightIcon aria-hidden="true" className="size-3 shrink-0 self-center" />
          <span className="wrap-anywhere">
            <span className="sr-only">Requested: </span>
            {formatPositiveKeywordValue(field, value, currencyCode)}
          </span>
        </p>
      ) : null}
    </Field>
  )
}

function sameFieldValue(
  field: PatchField,
  before: MutableKeywordState[PatchField],
  value: MutableKeywordState[PatchField]
): boolean {
  if (field === "cpc_bid" && typeof before === "string" && typeof value === "string") {
    return Number(before) === Number(value)
  }
  if (isRecord(before) && isRecord(value)) {
    return (
      Object.keys(before).length === Object.keys(value).length &&
      Object.entries(before).every(([key, entry]) => value[key] === entry)
    )
  }
  return JSON.stringify(before) === JSON.stringify(value)
}

function PatchValueInput({
  disabled,
  field,
  id,
  label,
  onChange,
  value,
}: {
  disabled: boolean
  field: PatchField
  id: string
  label: string
  onChange: (value: MutableKeywordState[PatchField]) => void
  value: MutableKeywordState[PatchField]
}) {
  const specification = POSITIVE_KEYWORD_PATCH_FIELDS_BY_KEY.get(field)
  if (!specification) return null
  if (specification.valueFamily === "status") {
    return (
      <StatusInput disabled={disabled} id={id} label={label} onChange={onChange} value={value} />
    )
  }
  if (specification.valueFamily === "urlList") {
    return (
      <ListFieldInput
        ariaLabel={label}
        disabled={disabled}
        id={id}
        onChange={onChange}
        placeholder="Enter a URL and press Enter"
        value={Array.isArray(value) ? value : []}
      />
    )
  }
  if (specification.valueFamily === "parameters") {
    return (
      <KeyValueFieldInput
        ariaLabel={label}
        disabled={disabled}
        id={id}
        lockedEntries={[]}
        maxEntries={8}
        onChange={(nextValue) => {
          onChange(nextValue as Record<string, string>)
        }}
        value={isRecord(value) ? value : {}}
      />
    )
  }
  return (
    <ScalarPatchInput
      disabled={disabled}
      id={id}
      label={label}
      numeric={specification.valueFamily === "number"}
      onChange={onChange}
      value={value}
    />
  )
}

function StatusInput({ disabled, id, label, onChange, value }: PatchInputProps) {
  const status = value === "ENABLED" || value === "PAUSED" ? value : "ENABLED"
  return (
    <Select<PositiveKeywordStatus>
      disabled={disabled}
      onValueChange={(nextValue) => {
        if (nextValue !== null) onChange(nextValue)
      }}
      value={status}
    >
      <SelectTrigger aria-label={label} className="w-full" id={id}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent align="start">
        <SelectGroup>
          <SelectItem label="Enabled" value="ENABLED">
            Enabled
          </SelectItem>
          <SelectItem label="Paused" value="PAUSED">
            Paused
          </SelectItem>
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}

type PatchInputProps = {
  disabled: boolean
  id: string
  label: string
  onChange: (value: MutableKeywordState[PatchField]) => void
  value: MutableKeywordState[PatchField]
}

function ScalarPatchInput({
  disabled,
  id,
  label,
  numeric,
  onChange,
  value,
}: PatchInputProps & { numeric: boolean }) {
  return (
    <Input
      aria-label={label}
      autoComplete="off"
      disabled={disabled}
      id={id}
      inputMode={numeric ? "decimal" : undefined}
      onChange={(event) => {
        const next = event.currentTarget.value
        if (numeric) onChange(next.trim() ? Number(next) : null)
        else onChange(next || null)
      }}
      type={numeric ? "number" : "text"}
      value={typeof value === "string" || typeof value === "number" ? value : ""}
    />
  )
}

function hasAdvancedPatchField(patch: KeywordPatch): boolean {
  return POSITIVE_KEYWORD_PATCH_FIELDS.some(
    (field) => field.advanced && Object.hasOwn(patch, field.key)
  )
}

function withPatchField(
  patch: KeywordPatch,
  field: PatchField,
  value: MutableKeywordState[PatchField]
): KeywordPatch {
  return { ...patch, [field]: value }
}

function editablePatch(patch: KeywordPatch): Record<string, EditedRecordCell> {
  return Object.fromEntries(Object.entries(patch).map(([key, value]) => [key, value ?? ""]))
}

function toggleExpanded(current: Set<string>, identity: string): Set<string> {
  const next = new Set(current)
  if (next.has(identity)) next.delete(identity)
  else next.add(identity)
  return next
}
