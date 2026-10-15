// apps/web/src/integrations/meta_ads/components/insights-approval.tsx

import { useState } from "react"

import {
  ToolApprovalDecisionCard,
  type ToolApprovalDecisionControls,
} from "@/components/tool-ui/approval-card"
import { mergeApprovalArgs } from "@/components/tool-ui/approval-args"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Button } from "@/components/ui/button"
import { FieldSet } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { editApprovalFields } from "@/integrations/approval-edits"
import type { ToolActivity } from "@/integrations/contract"
import { MetaAdsLogo } from "@/integrations/meta_ads/components/logo"
import { InsightsFilters } from "@/integrations/meta_ads/components/insights-filters"
import { ReportChoice, ReportMultiChoice } from "@/integrations/meta_ads/components/report-choice"
import { SettingRow, SettingRows } from "@/integrations/meta_ads/components/setting-rows"
import {
  insightsApprovalError,
  insightsDatePresets,
  parseInsightsApproval,
} from "@/integrations/meta_ads/lib/insights-approval"
import { parseInsightsOptions } from "@/integrations/meta_ads/lib/insights-options"
import { pluralize, titleCaseToken } from "@/lib/format"

function intervalLabel(value: string | number): string {
  if (typeof value === "number") return value === 1 ? "Daily" : `Every ${String(value)} days`
  return value === "all_days" ? "Whole period" : titleCaseToken(value, value)
}

function listSummary(values: string[]): string {
  return values.length > 0 ? values.map((value) => titleCaseToken(value, value)).join(", ") : "None"
}

export function MetaAdsInsightsApproval({
  activity,
  controls,
  formSchema,
}: {
  activity: ToolActivity
  controls: ToolApprovalDecisionControls
  formSchema: unknown
}) {
  const options = parseInsightsOptions(formSchema)
  const args = options
    ? parseInsightsApproval(mergeApprovalArgs(activity.args, controls.decision.edits), options)
    : null
  const error = options
    ? insightsApprovalError(args, options)
    : "Report options are unavailable. Reload this page to try again, or decline the request."
  const disabled = Boolean(controls.disabled) || controls.decision.decision !== "pending"
  const [presets] = useState(() => insightsDatePresets(new Date()))
  const activePreset = args
    ? (presets.find((preset) => preset.since === args.since && preset.until === args.until)
        ?.label ?? "Custom")
    : "Custom"
  const levelOptions = (options?.levels ?? []).map((value) => ({
    value,
    label: value === "adset" ? "Ad Set" : titleCaseToken(value, value),
  }))
  const edit = (patch: Record<string, EditedValue>) => {
    editApprovalFields(controls, disabled, patch)
  }
  return (
    <ToolApprovalDecisionCard
      activityId={activity.id}
      args={activity.args}
      controls={controls}
      icon={<MetaAdsLogo className="size-5" />}
      label="Run Meta Ads Insights"
      toolName={activity.name}
      prompt="Review the dates and measures for this report."
      validationError={error}
      derivedFromUntrusted={activity.derivedFromUntrusted ?? false}
      taintSources={activity.taintSources ?? []}
    >
      {args && options ? (
        <FieldSet disabled={disabled}>
          <div className="grid gap-3">
            <div className="grid gap-2">
              <div aria-label="Date range" className="flex flex-wrap gap-1.5" role="radiogroup">
                {[...presets, { label: "Custom", since: "", until: "" }].map((preset) => {
                  const checked = preset.label === activePreset
                  return (
                    <Button
                      key={preset.label}
                      aria-checked={checked}
                      className="h-8 rounded-full"
                      disabled={disabled}
                      onClick={() => {
                        if (preset.since) edit({ since: preset.since, until: preset.until })
                        else document.getElementById(`${activity.id}-since`)?.focus()
                      }}
                      role="radio"
                      size="sm"
                      type="button"
                      variant={checked ? "secondary" : "outline"}
                    >
                      {preset.label}
                    </Button>
                  )
                })}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  aria-label="Start date"
                  className="h-8 w-40"
                  id={`${activity.id}-since`}
                  max={args.until || undefined}
                  onChange={(event) => {
                    edit({ since: event.currentTarget.value })
                  }}
                  required
                  type="date"
                  value={args.since}
                />
                <span className="text-sm">to</span>
                <Input
                  aria-label="End date"
                  className="h-8 w-40"
                  id={`${activity.id}-until`}
                  min={args.since || undefined}
                  onChange={(event) => {
                    edit({ until: event.currentTarget.value })
                  }}
                  required
                  type="date"
                  value={args.until}
                />
                <span className="text-muted-foreground text-sm">
                  Each Account&rsquo;s Time Zone
                </span>
              </div>
            </div>
            <SettingRows ariaLabel="Report settings" defaultOpen="fields">
              <SettingRow
                rowKey="level"
                summary={
                  levelOptions.find((item) => item.value === args.level)?.label ?? args.level
                }
                title="Report By"
              >
                <div
                  aria-label="Report By"
                  className="bg-muted flex w-fit flex-wrap rounded-lg p-0.5"
                  role="radiogroup"
                >
                  {levelOptions.map((item) => (
                    <Button
                      key={item.value}
                      aria-checked={item.value === args.level}
                      className="h-8"
                      disabled={disabled}
                      onClick={() => {
                        edit({ level: item.value })
                      }}
                      role="radio"
                      size="sm"
                      type="button"
                      variant={item.value === args.level ? "outline" : "ghost"}
                    >
                      {item.label}
                    </Button>
                  ))}
                </div>
              </SettingRow>
              <SettingRow rowKey="fields" summary={listSummary(args.fields)} title="Measures">
                <ReportMultiChoice
                  allowCustom
                  disabled={disabled}
                  hideLabel
                  id={`${activity.id}-fields`}
                  label="Measures"
                  onChange={(value) => {
                    edit({ fields: value })
                  }}
                  options={options.fields.values}
                  value={args.fields}
                />
                <p className="text-muted-foreground text-sm">
                  Search common measures, or enter another Meta field name. Campaign and account
                  names are always included.
                </p>
              </SettingRow>
              <SettingRow
                rowKey="interval"
                summary={intervalLabel(args.time_increment)}
                title="Interval"
              >
                <ReportChoice
                  disabled={disabled}
                  hideLabel
                  id={`${activity.id}-interval`}
                  label="Interval"
                  onChange={(value) => {
                    const interval = options.intervals.find((item) => String(item) === value)
                    if (interval !== undefined) edit({ time_increment: interval })
                  }}
                  options={options.intervals.map((value) => ({
                    value: String(value),
                    label: intervalLabel(value),
                  }))}
                  value={String(args.time_increment)}
                />
                <p className="text-muted-foreground text-sm">
                  Daily splits each row into one per day.
                </p>
              </SettingRow>
              <SettingRow
                rowKey="breakdowns"
                summary={listSummary([...args.breakdowns, ...args.action_breakdowns])}
                title="Breakdowns"
              >
                <ReportMultiChoice
                  disabled={disabled}
                  id={`${activity.id}-breakdowns`}
                  label="Breakdowns"
                  onChange={(value) => {
                    edit({ breakdowns: value })
                  }}
                  options={options.breakdowns.values}
                  value={args.breakdowns}
                />
                <ReportMultiChoice
                  disabled={disabled}
                  id={`${activity.id}-actions`}
                  label="Action Breakdowns"
                  onChange={(value) => {
                    edit({ action_breakdowns: value })
                  }}
                  options={options.actionBreakdowns.values}
                  value={args.action_breakdowns}
                />
              </SettingRow>
              <SettingRow
                rowKey="attribution"
                summary={
                  args.attribution_windows.length > 0
                    ? listSummary(args.attribution_windows)
                    : "Default: each ad set\u2019s own setting"
                }
                title="Attribution"
              >
                <ReportMultiChoice
                  disabled={disabled}
                  hideLabel
                  id={`${activity.id}-attribution`}
                  label="Attribution Windows"
                  onChange={(value) => {
                    edit({ attribution_windows: value.length ? value : null })
                  }}
                  options={options.attributionWindows.values}
                  value={args.attribution_windows}
                />
                <p className="text-muted-foreground text-sm">
                  Leave this empty to use each ad set&rsquo;s settings.
                </p>
              </SettingRow>
              <SettingRow
                rowKey="sort"
                summary={`${args.sort ? titleCaseToken(args.sort, args.sort) : "Default order"} \u00b7 ${
                  args.filters.length > 0
                    ? `${String(args.filters.length)} ${pluralize(args.filters.length, "filter")}`
                    : "no filters"
                }`}
                title="Sort and Filter"
              >
                <ReportChoice
                  disabled={disabled}
                  id={`${activity.id}-sort`}
                  label="Sort Order"
                  onChange={(value) => {
                    edit({ sort: value })
                  }}
                  options={[
                    { value: "", label: "Default order" },
                    ...args.fields.flatMap((field) =>
                      options.sortDirections.map((direction) => ({
                        value: `${field}_${direction}`,
                        label: `${titleCaseToken(field, field)} (${direction})`,
                      }))
                    ),
                  ]}
                  value={args.sort}
                />
                <InsightsFilters
                  disabled={disabled}
                  fields={args.fields}
                  id={`${activity.id}-filters`}
                  onChange={(value) => {
                    edit({ filters: value })
                  }}
                  options={options}
                  value={args.filters}
                />
              </SettingRow>
              <SettingRow rowKey="rows" summary={String(args.limit)} title="Maximum Rows">
                <Input
                  aria-label="Maximum Rows"
                  className="h-8 w-40"
                  id={`${activity.id}-limit`}
                  max={options.rows.max}
                  min={options.rows.min}
                  onChange={(event) => {
                    edit({ limit: Number(event.currentTarget.value) })
                  }}
                  step={1}
                  type="number"
                  value={Number.isFinite(args.limit) ? args.limit : ""}
                />
                <p className="text-muted-foreground text-sm">
                  {options.rows.min.toLocaleString()} to {options.rows.max.toLocaleString()}.
                </p>
              </SettingRow>
            </SettingRows>
          </div>
        </FieldSet>
      ) : null}
    </ToolApprovalDecisionCard>
  )
}
