// apps/web/src/features/schedules/components/schedule-review-section.tsx

import type { ReactNode } from "react"
import { ChevronDownIcon, ClipboardCheckIcon } from "lucide-react"

import { FormSection } from "@/components/forms/form-section"
import { Checkbox } from "@/components/ui/checkbox"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { AgentIdentityIcon } from "@/features/agents/components/agent-identity-icon"
import type { Agent } from "@/features/agents/types"
import {
  MAX_SCHEDULE_BUDGET,
  type ScheduleFormFieldSetter,
  type ScheduleFormState,
} from "@/features/schedules/components/schedule-form-model"
import { formatScheduleFormCadence } from "@/features/schedules/format"
import { SchedulePreviewResult } from "@/features/schedules/components/schedule-preview-panel"
import type { SchedulePreviewView } from "@/features/schedules/components/use-schedule-preview"

export function ScheduleReviewSection({
  activeContextLabel,
  budgetErrors,
  completionCriteriaError,
  preview,
  selectedAgent,
  setField,
  state,
}: {
  activeContextLabel: string
  budgetErrors: {
    requests: string | undefined
    totalTokens: string | undefined
  }
  completionCriteriaError: string | undefined
  preview: SchedulePreviewView
  selectedAgent: Agent | null
  setField: ScheduleFormFieldSetter
  state: ScheduleFormState
}) {
  return (
    <FormSection
      description="Check what will run, then choose whether it starts active and can make lasting changes."
      eyebrow="Review"
      icon={<ClipboardCheckIcon className="size-4" />}
      title="Schedule summary"
    >
      <div className="flex flex-col gap-6">
        <dl className="divide-border overflow-hidden rounded-md border">
          <ReviewRow label="Name">{state.name.trim()}</ReviewRow>
          <ReviewRow label="Agent">
            {selectedAgent ? (
              <span className="flex min-w-0 items-center gap-2">
                <AgentIdentityIcon
                  agentId={selectedAgent.id}
                  decorative
                  name={selectedAgent.name}
                  size="sm"
                />
                <span className="truncate">{selectedAgent.name}</span>
              </span>
            ) : (
              "Assigned agent unavailable"
            )}
          </ReviewRow>
          <ReviewRow label="Prompt">
            <span className="whitespace-pre-wrap">{state.defaultPrompt.trim()}</span>
          </ReviewRow>
          <ReviewRow label="Cadence">{formatScheduleFormCadence(state)}</ReviewRow>
          <ReviewRow label="Timezone">{state.timezone}</ReviewRow>
          <ReviewRow label="Active context">{activeContextLabel}</ReviewRow>
          <ReviewRow label="Completion check">
            {state.completionReportRequired
              ? `${String(completionCriteriaCount(state.completionCriteria))} required`
              : "Not required"}
          </ReviewRow>
        </dl>

        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium">Upcoming runs</h3>
          <SchedulePreviewResult preview={preview} />
        </div>

        <div className="flex flex-col gap-3 border-t pt-5">
          <div>
            <h3 className="text-sm font-medium">Options</h3>
            <p className="text-muted-foreground mt-1 text-sm">
              These settings can be changed later.
            </p>
          </div>
          <FieldGroup className="gap-1">
            <ScheduleOptionField
              checked={state.isActive}
              description="Start running on schedule as soon as it's created. Turn this off to create or keep it paused."
              id="schedule-active"
              label="Active"
              onCheckedChange={(checked) => {
                setField("isActive", checked)
              }}
            />
            <ScheduleOptionField
              checked={state.externalWritesAllowed}
              description="Let runs change connected apps or permanent files. Leave this off for read-only schedules."
              id="schedule-external-writes"
              label="Allow external writes"
              onCheckedChange={(checked) => {
                setField("externalWritesAllowed", checked)
              }}
            />
          </FieldGroup>

          <details
            className="group rounded-md border"
            open={
              completionCriteriaError || budgetErrors.requests || budgetErrors.totalTokens
                ? true
                : undefined
            }
          >
            <summary className="focus-visible:ring-ring flex cursor-pointer list-none items-center justify-between gap-3 rounded-md px-4 py-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-offset-2 [&::-webkit-details-marker]:hidden">
              <span>
                <span className="font-medium">Advanced</span>
                <span className="text-muted-foreground ml-2">Checks and budgets</span>
              </span>
              <ChevronDownIcon
                aria-hidden="true"
                className="text-muted-foreground size-4 transition-transform group-open:rotate-180"
              />
            </summary>
            <div className="flex flex-col gap-4 border-t p-4">
              <ScheduleOptionField
                checked={state.completionReportRequired}
                description="Ask the agent to report whether every check passed before the run finishes."
                id="schedule-completion-required"
                label="Require a completion report"
                onCheckedChange={(checked) => {
                  setField("completionReportRequired", checked)
                }}
              />
              {state.completionReportRequired ? (
                <Field data-invalid={completionCriteriaError ? true : undefined}>
                  <FieldLabel htmlFor="schedule-completion-criteria">Completion checks</FieldLabel>
                  <Textarea
                    aria-invalid={completionCriteriaError ? true : undefined}
                    className="min-h-28"
                    id="schedule-completion-criteria"
                    onChange={(event) => {
                      setField("completionCriteria", event.currentTarget.value)
                    }}
                    placeholder={"A report was created\nEvery account was reviewed"}
                    value={state.completionCriteria}
                  />
                  <p className="text-muted-foreground text-sm">
                    Add one plain-language check per line. The run needs attention if any check
                    fails or the agent does not report.
                  </p>
                  <FieldError>{completionCriteriaError}</FieldError>
                </Field>
              ) : null}
              <div className="grid gap-4 sm:grid-cols-2">
                <BudgetField
                  description="Maximum model requests for each run. Leave blank to use the agent default."
                  error={budgetErrors.requests}
                  id="schedule-max-requests"
                  label="Request budget"
                  onChange={(value) => {
                    setField("maxRequests", value)
                  }}
                  value={state.maxRequests}
                />
                <BudgetField
                  description="Maximum input and output tokens combined. Leave blank to use the platform default."
                  error={budgetErrors.totalTokens}
                  id="schedule-max-total-tokens"
                  label="Total token budget"
                  onChange={(value) => {
                    setField("maxTotalTokens", value)
                  }}
                  value={state.maxTotalTokens}
                />
              </div>
            </div>
          </details>
        </div>
      </div>
    </FormSection>
  )
}

function BudgetField({
  description,
  error,
  id,
  label,
  onChange,
  value,
}: {
  description: string
  error: string | undefined
  id: string
  label: string
  onChange: (value: string) => void
  value: string
}) {
  return (
    <Field data-invalid={error ? true : undefined}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input
        aria-invalid={error ? true : undefined}
        id={id}
        inputMode="numeric"
        max={MAX_SCHEDULE_BUDGET}
        min={1}
        onChange={(event) => {
          onChange(event.currentTarget.value)
        }}
        placeholder="Use default"
        step={1}
        type="number"
        value={value}
      />
      <p className="text-muted-foreground text-sm">{description}</p>
      <FieldError>{error}</FieldError>
    </Field>
  )
}

function completionCriteriaCount(value: string) {
  return value.split("\n").filter((criterion) => criterion.trim()).length
}

function ScheduleOptionField({
  checked,
  description,
  id,
  label,
  onCheckedChange,
}: {
  checked: boolean
  description: string
  id: string
  label: string
  onCheckedChange: (checked: boolean) => void
}) {
  return (
    <Field>
      <FieldLabel
        className="hover:bg-muted/40 focus-within:bg-muted/40 has-checked:bg-primary/5 dark:has-checked:bg-primary/10 w-full cursor-pointer items-start gap-3 rounded-md p-3 transition-colors"
        htmlFor={id}
      >
        <Checkbox checked={checked} className="mt-0.5" id={id} onCheckedChange={onCheckedChange} />
        <span className="flex min-w-0 flex-col gap-1">
          <span className="text-sm font-medium">{label}</span>
          <span className="text-muted-foreground text-left text-sm leading-normal font-normal">
            {description}
          </span>
        </span>
      </FieldLabel>
    </Field>
  )
}

function ReviewRow({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div className="grid gap-1 px-4 py-3 sm:grid-cols-[9rem_minmax(0,1fr)] sm:gap-4">
      <dt className="text-muted-foreground text-sm">{label}</dt>
      <dd className="min-w-0 text-sm font-medium">{children}</dd>
    </div>
  )
}
