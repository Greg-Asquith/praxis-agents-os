// apps/web/src/features/agents/components/agent-state-section.tsx

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import type { AgentFormFieldSetter, AgentFormState } from "@/features/agents/components/agent-form-model"

export function AgentStateSection({
  setField,
  skillIds,
  state,
}: {
  setField: AgentFormFieldSetter
  skillIds: string[]
  state: AgentFormState
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>State</CardTitle>
        <CardDescription>Operational visibility and availability controls.</CardDescription>
      </CardHeader>
      <CardContent>
        <FieldGroup>
          <div className="grid gap-4 md:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="agent-active">Availability</FieldLabel>
              <Select
                onValueChange={(value) => {
                  setField("isActive", value === "false" ? "false" : "true")
                }}
                value={state.isActive}
              >
                <SelectTrigger id="agent-active" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="start">
                  <SelectGroup>
                    <SelectItem value="true">Active</SelectItem>
                    <SelectItem value="false">Inactive</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>

            <Field>
              <FieldLabel htmlFor="agent-favorite">Favorite</FieldLabel>
              <Select
                onValueChange={(value) => {
                  setField("isFavorite", value === "true" ? "true" : "false")
                }}
                value={state.isFavorite}
              >
                <SelectTrigger id="agent-favorite" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="start">
                  <SelectGroup>
                    <SelectItem value="false">No</SelectItem>
                    <SelectItem value="true">Yes</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
          </div>

          <Field>
            <FieldLabel htmlFor="agent-skills">Skills</FieldLabel>
            <Textarea
              className="min-h-20 font-mono text-xs"
              disabled
              id="agent-skills"
              value={skillIds.join("\n")}
            />
            <FieldDescription>
              Skill attachment is read-only here until the skill management flow is public.
            </FieldDescription>
          </Field>
        </FieldGroup>
      </CardContent>
    </Card>
  )
}
