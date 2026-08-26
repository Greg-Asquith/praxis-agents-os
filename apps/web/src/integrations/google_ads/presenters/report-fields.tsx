// apps/web/src/integrations/google_ads/presenters/report-fields.tsx

import { ChevronDownIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Skeleton } from "@/components/ui/skeleton"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { CopyTextButton } from "@/components/ui/copy-text-button"
import type { ToolRowPresenter } from "@/integrations/contract"
import { GoogleAdsToolHeading } from "@/integrations/google_ads/components/tool-heading"
import { titleCaseToken } from "@/lib/format"
import { isRecord } from "@/lib/guards"

const LIST_TOOL = "google_ads_list_report_fields"
const GET_TOOL = "google_ads_get_report_field"
const MAX_VALUES = 100

const FIELD_COLUMNS: DataColumn[] = [
  { key: "name", kind: "id", label: "API name", width: 240 },
  { key: "category", kind: "text", label: "Category" },
  { key: "data_type", kind: "text", label: "Data type" },
  { key: "selectable", kind: "badge", label: "Selectable" },
  { key: "filterable", kind: "badge", label: "Filterable" },
  { key: "sortable", kind: "badge", label: "Sortable" },
  { key: "is_repeated", kind: "badge", label: "Repeated" },
]

type ReportField = {
  category: string
  dataType: string
  filterable: boolean
  isRepeated: boolean
  name: string
  selectable: boolean
  sortable: boolean
}

type ListReportFields = {
  apiVersion: string
  attributeResourceCount: number
  attributeResources: string[]
  compatibilityTruncated: boolean
  fieldCount: number
  fields: ReportField[]
  metricCount: number
  metrics: string[]
  resource: string
  segmentCount: number
  segments: string[]
  truncated: boolean
}

type GetReportField = ReportField & {
  apiVersion: string
  attributeResources: string[]
  enumValues: string[]
  metrics: string[]
  segments: string[]
  selectableWith: string[]
  typeUrl: string | null
}

type CollectionAccent = "blue" | "green" | "red" | "yellow"

export const googleAdsReportFieldsPresenter: ToolRowPresenter = {
  key: "google-ads-report-fields",
  matches: (activity) => activity.name === LIST_TOOL || activity.name === GET_TOOL,
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return reportFieldsSkeleton(activity.name === GET_TOOL)
    }
    if (activity.name === LIST_TOOL) {
      const result = parseListReportFields(activity.result)
      return result
        ? listReportFieldsResult(defaultOpen, result, listReportFieldSearch(activity.args))
        : null
    }
    if (activity.name === GET_TOOL) {
      const result = parseGetReportField(activity.result)
      return result ? getReportFieldResult(defaultOpen, result) : null
    }
    return null
  },
}

function reportFieldsSkeleton(exact: boolean) {
  const action = exact ? "Getting" : "Listing"
  const heading = exact ? "Get Google Ads Report Field" : "List Google Ads Report Fields"
  return (
    <section
      aria-busy="true"
      aria-label={`${action} Google Ads report field metadata`}
      className="border-border grid gap-3 rounded-lg border p-3"
    >
      <GoogleAdsToolHeading>{heading}</GoogleAdsToolHeading>
      <Skeleton className="h-9 w-full" />
      <Skeleton className="h-9 w-full" />
      <Skeleton className="h-9 w-4/5" />
    </section>
  )
}

function listReportFieldsResult(
  defaultOpen: boolean,
  result: ListReportFields,
  search: string | null
) {
  const rows = result.fields.map(fieldRow)
  const fieldsShortened = rows.length < result.fieldCount
  const compatibilityShortened =
    result.compatibilityTruncated ||
    result.metrics.length < result.metricCount ||
    result.segments.length < result.segmentCount
  return (
    <ToolResultCard
      ariaLabel="Google Ads report fields"
      defaultOpen={defaultOpen}
      details={[
        { label: "Resource", value: result.resource },
        { label: "Search", value: search ?? "All fields" },
        { label: "Matches", value: matchSummary(result) },
        {
          label: "Resource fields",
          summary: false,
          value: result.fieldCount.toLocaleString(),
        },
        { label: "Metrics", summary: false, value: result.metricCount.toLocaleString() },
        { label: "Segments", summary: false, value: result.segmentCount.toLocaleString() },
        { label: "API version", summary: false, value: result.apiVersion },
      ]}
      heading={<GoogleAdsToolHeading>List Google Ads Report Fields</GoogleAdsToolHeading>}
      trailing={<Badge variant="success">Done</Badge>}
    >
      <div className="grid min-w-0 gap-4">
        {copyableName("Resource", result.resource)}
        {rows.length > 0 ? (
          <DataTable
            columns={FIELD_COLUMNS}
            exportFilename={`google-ads-${result.resource}-report-fields.csv`}
            pageSize={25}
            rows={rows}
            truncationNote={
              fieldsShortened
                ? `${rows.length.toLocaleString()} of ${result.fieldCount.toLocaleString()} fields shown.`
                : null
            }
          />
        ) : (
          <p className="text-muted-foreground py-3 text-sm">
            {search
              ? `No resource fields matched “${search}”. Compatible metrics and segments appear below.`
              : "No resource fields were returned. Compatible metrics and segments appear below."}
          </p>
        )}
        {result.truncated && !fieldsShortened ? (
          <p className="text-warning-foreground text-xs">
            Google Ads reports more matching fields or compatibility values than this result
            includes.
          </p>
        ) : null}
        {compatibilityShortened ? (
          <p className="text-warning-foreground text-xs">
            One or more compatibility lists are shortened. Refine the search to narrow metrics and
            segments.
          </p>
        ) : null}
        <div className="grid gap-2">
          <h3 className="text-sm font-medium">Compatible fields</h3>
          {nameCollection({
            accent: "blue",
            emptyLabel: "No attribute resources returned.",
            label: "Attribute resources",
            names: result.attributeResources,
            totalCount: result.attributeResourceCount,
          })}
          {nameCollection({
            accent: "green",
            emptyLabel: "No compatible metrics returned.",
            label: "Metrics",
            names: result.metrics,
            totalCount: result.metricCount,
          })}
          {nameCollection({
            accent: "yellow",
            emptyLabel: "No compatible segments returned.",
            label: "Segments",
            names: result.segments,
            totalCount: result.segmentCount,
          })}
        </div>
      </div>
    </ToolResultCard>
  )
}

function getReportFieldResult(defaultOpen: boolean, result: GetReportField) {
  return (
    <ToolResultCard
      ariaLabel="Google Ads report field metadata"
      defaultOpen={defaultOpen}
      details={[
        { label: "Field", value: result.name },
        { label: "Category", value: humanizeToken(result.category) },
        { label: "API version", summary: false, value: result.apiVersion },
      ]}
      heading={<GoogleAdsToolHeading>Get Google Ads Report Field</GoogleAdsToolHeading>}
      trailing={<Badge variant="success">Done</Badge>}
    >
      <div className="grid min-w-0 gap-4">
        {copyableName("API name", result.name)}
        <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {metadataValue("Category", humanizeToken(result.category))}
          {metadataValue("Data type", humanizeToken(result.dataType))}
          {metadataValue("Type URL", result.typeUrl ?? "Not provided")}
          {metadataValue("API version", result.apiVersion)}
        </dl>
        {fieldFlags(result)}
        <div className="grid gap-2">
          <h3 className="text-sm font-medium">Values and compatibility</h3>
          {nameCollection({
            accent: "red",
            emptyLabel: "This field has no enum values.",
            label: "Enum values",
            names: result.enumValues,
          })}
          {nameCollection({
            accent: "blue",
            emptyLabel: "No selectable-with fields returned.",
            label: "Selectable with",
            names: result.selectableWith,
          })}
          {nameCollection({
            accent: "blue",
            emptyLabel: "No attribute resources returned.",
            label: "Attribute resources",
            names: result.attributeResources,
          })}
          {nameCollection({
            accent: "green",
            emptyLabel: "No compatible metrics returned.",
            label: "Metrics",
            names: result.metrics,
          })}
          {nameCollection({
            accent: "yellow",
            emptyLabel: "No compatible segments returned.",
            label: "Segments",
            names: result.segments,
          })}
        </div>
      </div>
    </ToolResultCard>
  )
}

function copyableName(label: string, value: string) {
  return (
    <div className="bg-muted/25 flex min-w-0 items-center justify-between gap-3 rounded-md border px-3 py-2">
      <div className="min-w-0">
        <p className="text-muted-foreground text-xs">{label}</p>
        <code className="block truncate text-sm" title={value}>
          {value}
        </code>
      </div>
      <CopyTextButton label={label} value={value} />
    </div>
  )
}

function metadataValue(label: string, value: string) {
  return (
    <div className="bg-muted/20 min-w-0 rounded-md border px-3 py-2">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="mt-0.5 truncate text-sm" title={value}>
        {value}
      </dd>
    </div>
  )
}

function fieldFlags(field: ReportField) {
  return (
    <dl aria-label="Report field capabilities" className="flex flex-wrap gap-2">
      {flag("Selectable", field.selectable)}
      {flag("Filterable", field.filterable)}
      {flag("Sortable", field.sortable)}
      {flag("Repeated", field.isRepeated)}
    </dl>
  )
}

function flag(label: string, value: boolean) {
  return (
    <div className="flex items-center gap-1.5">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd>
        <Badge variant={value ? "success" : "outline"}>{value ? "Yes" : "No"}</Badge>
      </dd>
    </div>
  )
}

function nameCollection({
  accent,
  emptyLabel,
  label,
  names,
  totalCount = names.length,
}: {
  accent: CollectionAccent
  emptyLabel: string
  label: string
  names: string[]
  totalCount?: number
}) {
  const countLabel =
    names.length < totalCount
      ? `${names.length.toLocaleString()} of ${totalCount.toLocaleString()}`
      : totalCount.toLocaleString()
  return (
    <details className="group min-w-0 rounded-md border">
      <summary className="focus-visible:ring-ring flex cursor-pointer list-none items-center justify-between gap-3 rounded-md px-3 py-2 text-xs font-medium outline-none focus-visible:ring-2 focus-visible:ring-offset-2 [&::-webkit-details-marker]:hidden">
        <span className="flex min-w-0 items-center gap-2">
          <span
            aria-hidden="true"
            className={`size-2 shrink-0 rounded-full ${accentClass(accent)}`}
          />
          <span className="truncate">{label}</span>
          <span className="text-muted-foreground font-normal">({countLabel})</span>
        </span>
        <ChevronDownIcon
          aria-hidden="true"
          className="text-muted-foreground size-3.5 shrink-0 transition-transform group-open:rotate-180"
        />
      </summary>
      <div className="grid min-w-0 gap-2 border-t p-3">
        {names.length > 0 ? (
          <>
            <div className="flex justify-end">
              <CopyTextButton label={label} text value={names.join("\n")} />
            </div>
            <ul className="grid min-w-0 gap-1 sm:grid-cols-2">
              {names.map((name) => (
                <li className="bg-muted/25 min-w-0 rounded px-2 py-1" key={name}>
                  <code className="block truncate text-xs" title={name}>
                    {name}
                  </code>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="text-muted-foreground text-xs">{emptyLabel}</p>
        )}
      </div>
    </details>
  )
}

function parseListReportFields(value: unknown): ListReportFields | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["api_version"]) ||
    !isNonEmptyString(value["resource"]) ||
    !Array.isArray(value["attribute_resources"]) ||
    !isCount(value["attribute_resource_count"]) ||
    !Array.isArray(value["metrics"]) ||
    !isCount(value["metric_count"]) ||
    !Array.isArray(value["segments"]) ||
    !isCount(value["segment_count"]) ||
    typeof value["compatibility_truncated"] !== "boolean" ||
    !Array.isArray(value["fields"]) ||
    !isCount(value["field_count"]) ||
    typeof value["truncated"] !== "boolean"
  )
    return null
  const attributeResources = parseBoundedNames(value["attribute_resources"])
  const metrics = parseBoundedNames(value["metrics"])
  const segments = parseBoundedNames(value["segments"])
  const fields = parseFields(value["fields"])
  if (
    !attributeResources ||
    !metrics ||
    !segments ||
    !fields ||
    attributeResources.length > value["attribute_resource_count"] ||
    metrics.length > value["metric_count"] ||
    segments.length > value["segment_count"] ||
    fields.length > value["field_count"]
  )
    return null
  return {
    apiVersion: value["api_version"],
    attributeResourceCount: value["attribute_resource_count"],
    attributeResources,
    compatibilityTruncated: value["compatibility_truncated"],
    fieldCount: value["field_count"],
    fields,
    metricCount: value["metric_count"],
    metrics,
    resource: value["resource"],
    segmentCount: value["segment_count"],
    segments,
    truncated: value["truncated"],
  }
}

function listReportFieldSearch(value: unknown): string | null {
  if (!isRecord(value) || typeof value["search"] !== "string") return null
  return value["search"].trim() || null
}

function matchSummary(result: ListReportFields): string {
  const matches: string[] = []
  if (result.fieldCount > 0) {
    matches.push(countLabel(result.fieldCount, "resource field"))
  }
  if (result.metricCount > 0) {
    matches.push(countLabel(result.metricCount, "metric"))
  }
  if (result.segmentCount > 0) {
    matches.push(countLabel(result.segmentCount, "segment"))
  }
  return matches.length > 0 ? matches.join(", ") : "No matches"
}

function countLabel(count: number, singular: string): string {
  return `${count.toLocaleString()} ${count === 1 ? singular : `${singular}s`}`
}

function parseGetReportField(value: unknown): GetReportField | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["api_version"]) ||
    (value["type_url"] !== null && !isNonEmptyString(value["type_url"])) ||
    !Array.isArray(value["enum_values"]) ||
    !Array.isArray(value["selectable_with"]) ||
    !Array.isArray(value["attribute_resources"]) ||
    !Array.isArray(value["metrics"]) ||
    !Array.isArray(value["segments"])
  )
    return null
  const field = parseField(value)
  const enumValues = parseNames(value["enum_values"])
  const selectableWith = parseNames(value["selectable_with"])
  const attributeResources = parseNames(value["attribute_resources"])
  const metrics = parseNames(value["metrics"])
  const segments = parseNames(value["segments"])
  if (!field || !enumValues || !selectableWith || !attributeResources || !metrics || !segments)
    return null
  return {
    ...field,
    apiVersion: value["api_version"],
    attributeResources,
    enumValues,
    metrics,
    segments,
    selectableWith,
    typeUrl: value["type_url"],
  }
}

function parseFields(values: unknown[]): ReportField[] | null {
  if (values.length > MAX_VALUES) return null
  const fields: ReportField[] = []
  for (const value of values) {
    const field = parseField(value)
    if (!field) return null
    fields.push(field)
  }
  return fields
}

function parseField(value: unknown): ReportField | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["name"]) ||
    !isNonEmptyString(value["category"]) ||
    !isNonEmptyString(value["data_type"]) ||
    typeof value["selectable"] !== "boolean" ||
    typeof value["filterable"] !== "boolean" ||
    typeof value["sortable"] !== "boolean" ||
    typeof value["is_repeated"] !== "boolean"
  )
    return null
  return {
    category: value["category"],
    dataType: value["data_type"],
    filterable: value["filterable"],
    isRepeated: value["is_repeated"],
    name: value["name"],
    selectable: value["selectable"],
    sortable: value["sortable"],
  }
}

function parseBoundedNames(values: unknown[]): string[] | null {
  if (values.length > MAX_VALUES) return null
  return parseNames(values)
}

function parseNames(values: unknown[]): string[] | null {
  if (!values.every(isNonEmptyString)) return null
  return values
}

function fieldRow(field: ReportField): DataRow {
  return {
    category: humanizeToken(field.category),
    data_type: humanizeToken(field.dataType),
    filterable: field.filterable ? "Yes" : "No",
    is_repeated: field.isRepeated ? "Yes" : "No",
    name: field.name,
    selectable: field.selectable ? "Yes" : "No",
    sortable: field.sortable ? "Yes" : "No",
  }
}

function humanizeToken(value: string): string {
  return titleCaseToken(value.toLowerCase(), value)
}

function accentClass(accent: CollectionAccent): string {
  if (accent === "blue") return "bg-[#4285f4]"
  if (accent === "green") return "bg-[#34a853]"
  if (accent === "red") return "bg-[#ea4335]"
  return "bg-[#fbbc04]"
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
}
