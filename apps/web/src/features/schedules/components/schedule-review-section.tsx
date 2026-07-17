// apps/web/src/features/schedules/components/schedule-review-section.tsx

import type { ReactNode } from "react"
import { ClipboardCheckIcon } from "lucide-react"

import { FormSection } from "@/components/forms/form-section"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { AgentIdentityIcon } from "@/features/agents/components/agent-identity-icon"
import type { Agent } from "@/features/agents/types"
import { formatScheduleFormCadence } from "@/features/schedules/format"
import type {
  ScheduleFormFieldSetter,
  ScheduleFormState,
} from "@/features/schedules/components/schedule-form-model"
import { SchedulePreviewResult } from "@/features/schedules/components/schedule-preview-panel"
import type { SchedulePreviewView } from "@/features/schedules/components/use-schedule-preview"

export function ScheduleReviewSection({
  preview,
  selectedAgent,
  setField,
  state,
}: {
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
        </div>
      </div>
    </FormSection>
  )
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
        <input
          checked={checked}
          className="border-input text-primary focus-visible:ring-ring/50 mt-0.5 size-4 shrink-0 rounded border"
          id={id}
          onChange={(event) => {
            onCheckedChange(event.currentTarget.checked)
          }}
          type="checkbox"
        />
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
