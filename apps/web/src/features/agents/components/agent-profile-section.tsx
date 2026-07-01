// apps/web/src/features/agents/components/agent-profile-section.tsx

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import type { AgentFormFieldSetter, AgentFormState } from "@/features/agents/components/agent-form-model"

export function AgentProfileSection({
  mode,
  setField,
  state,
}: {
  mode: "create" | "edit"
  setField: AgentFormFieldSetter
  state: AgentFormState
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Profile</CardTitle>
        <CardDescription>Name, routing slug, and operating instructions.</CardDescription>
      </CardHeader>
      <CardContent>
        <FieldGroup>
          <div className="grid gap-4 md:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="agent-name">Name</FieldLabel>
              <Input
                id="agent-name"
                onChange={(event) => {
                  setField("name", event.currentTarget.value)
                }}
                required
                value={state.name}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="agent-slug">Slug</FieldLabel>
              <Input
                id="agent-slug"
                onChange={(event) => {
                  setField("slug", event.currentTarget.value)
                }}
                placeholder={mode === "create" ? "Generated from name" : undefined}
                required={mode === "edit"}
                value={state.slug}
              />
            </Field>
          </div>

          <Field>
            <FieldLabel htmlFor="agent-description">Description</FieldLabel>
            <Textarea
              className="min-h-20"
              id="agent-description"
              onChange={(event) => {
                setField("description", event.currentTarget.value)
              }}
              value={state.description}
            />
          </Field>

          <Field>
            <FieldLabel htmlFor="agent-instructions">Instructions</FieldLabel>
            <Textarea
              className="min-h-48"
              id="agent-instructions"
              onChange={(event) => {
                setField("instructions", event.currentTarget.value)
              }}
              required
              value={state.instructions}
            />
            <FieldDescription>
              These instructions become the agent system prompt for workspace runs.
            </FieldDescription>
          </Field>
        </FieldGroup>
      </CardContent>
    </Card>
  )
}
