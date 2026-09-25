// apps/web/src/integrations/meta_ads/components/insights-approval.tsx

import {
  ToolApprovalDecisionCard,
  type ToolApprovalDecisionControls,
} from "@/components/tool-ui/approval-card"
import { mergeApprovalArgs } from "@/components/tool-ui/approval-args"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldSet } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import type { ToolActivity } from "@/integrations/contract"
import { MetaAdsLogo } from "@/integrations/meta_ads/components/logo"
import { InsightsFilters } from "@/integrations/meta_ads/components/insights-filters"
import { ReportChoice, ReportMultiChoice } from "@/integrations/meta_ads/components/report-choice"
import {
  insightsApprovalError,
  parseInsightsApproval,
} from "@/integrations/meta_ads/lib/insights-approval"
import { titleCaseToken } from "@/lib/format"

import { parseInsightsOptions } from "@/integrations/meta_ads/lib/insights-options"

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
  const edit = (key: string, value: EditedValue) => {
    controls.onDecisionChange({
      decision: "pending",
      edits: { ...controls.decision.edits, [key]: value },
      message: "",
    })
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
          <FieldGroup>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field>
                <FieldLabel htmlFor={`${activity.id}-since`}>Start date</FieldLabel>
                <Input
                  id={`${activity.id}-since`}
                  type="date"
                  required
                  value={args.since}
                  max={args.until || undefined}
                  onChange={(event) => {
                    edit("since", event.currentTarget.value)
                  }}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor={`${activity.id}-until`}>End date</FieldLabel>
                <Input
                  id={`${activity.id}-until`}
                  type="date"
                  required
                  value={args.until}
                  min={args.since || undefined}
                  onChange={(event) => {
                    edit("until", event.currentTarget.value)
                  }}
                />
              </Field>
            </div>
            <FieldDescription>Dates use each ad account’s time zone.</FieldDescription>
            <ReportChoice
              id={`${activity.id}-level`}
              label="Report by"
              value={args.level}
              options={options.levels.map((value) => ({
                value,
                label: value === "adset" ? "Ad set" : titleCaseToken(value, value),
              }))}
              disabled={disabled}
              onChange={(value) => {
                edit("level", value)
              }}
            />
            <ReportMultiChoice
              id={`${activity.id}-fields`}
              label="Report fields"
              value={args.fields}
              options={options.fields.values}
              disabled={disabled}
              onChange={(value) => {
                edit("fields", value)
              }}
              allowCustom
            />
            <FieldDescription>
              Search common measures, or enter another Meta field name. Campaign and account
              identifiers are included automatically.
            </FieldDescription>
            <details className="rounded-md border">
              <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
                Advanced options
              </summary>
              <FieldGroup className="border-t p-3">
                <div className="grid gap-3 sm:grid-cols-2">
                  <ReportChoice
                    id={`${activity.id}-interval`}
                    label="Report interval"
                    value={String(args.time_increment)}
                    options={options.intervals.map((value) => ({
                      value: String(value),
                      label:
                        typeof value === "number"
                          ? value === 1
                            ? "Daily"
                            : `Every ${String(value)} days`
                          : value === "all_days"
                            ? "Whole period"
                            : titleCaseToken(value, value),
                    }))}
                    disabled={disabled}
                    onChange={(value) => {
                      const interval = options.intervals.find((item) => String(item) === value)
                      if (interval !== undefined) edit("time_increment", interval)
                    }}
                  />
                  <Field>
                    <FieldLabel htmlFor={`${activity.id}-limit`}>Maximum rows</FieldLabel>
                    <Input
                      id={`${activity.id}-limit`}
                      type="number"
                      min={options.rows.min}
                      max={options.rows.max}
                      step={1}
                      value={Number.isFinite(args.limit) ? args.limit : ""}
                      onChange={(event) => {
                        edit("limit", Number(event.currentTarget.value))
                      }}
                    />
                  </Field>
                </div>
                <ReportMultiChoice
                  id={`${activity.id}-breakdowns`}
                  label="Breakdowns"
                  value={args.breakdowns}
                  options={options.breakdowns.values}
                  disabled={disabled}
                  onChange={(value) => {
                    edit("breakdowns", value)
                  }}
                />
                <ReportMultiChoice
                  id={`${activity.id}-actions`}
                  label="Action breakdowns"
                  value={args.action_breakdowns}
                  options={options.actionBreakdowns.values}
                  disabled={disabled}
                  onChange={(value) => {
                    edit("action_breakdowns", value)
                  }}
                />
                <ReportMultiChoice
                  id={`${activity.id}-attribution`}
                  label="Attribution windows"
                  value={args.attribution_windows}
                  options={options.attributionWindows.values}
                  disabled={disabled}
                  onChange={(value) => {
                    edit("attribution_windows", value.length ? value : null)
                  }}
                />
                <FieldDescription>
                  Leave attribution windows empty to use each ad set’s settings.
                </FieldDescription>
                <ReportChoice
                  id={`${activity.id}-sort`}
                  label="Sort order"
                  value={args.sort}
                  options={[
                    { value: "", label: "Default order" },
                    ...args.fields.flatMap((field) =>
                      options.sortDirections.map((direction) => ({
                        value: `${field}_${direction}`,
                        label: `${titleCaseToken(field, field)} (${direction})`,
                      }))
                    ),
                  ]}
                  disabled={disabled}
                  onChange={(value) => {
                    edit("sort", value)
                  }}
                />
                <InsightsFilters
                  id={`${activity.id}-filters`}
                  value={args.filters}
                  fields={args.fields}
                  options={options}
                  disabled={disabled}
                  onChange={(value) => {
                    edit("filters", value)
                  }}
                />
              </FieldGroup>
            </details>
          </FieldGroup>
        </FieldSet>
      ) : null}
    </ToolApprovalDecisionCard>
  )
}
