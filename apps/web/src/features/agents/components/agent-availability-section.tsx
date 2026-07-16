// apps/web/src/features/agents/components/agent-availability-section.tsx

import { FormSection } from "@/components/forms/form-section"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

export function AgentAvailabilitySection({
  isActive,
  isFavorite,
  onActiveChange,
  onFavoriteChange,
}: {
  isActive: "true" | "false"
  isFavorite: "true" | "false"
  onActiveChange: (isActive: "true" | "false") => void
  onFavoriteChange: (isFavorite: "true" | "false") => void
}) {
  return (
    <FormSection
      description="Control whether this agent can take on new work and how easy it is to find."
      eyebrow="State"
      title="Availability"
    >
      <FieldGroup className="grid gap-5 sm:grid-cols-2">
        <Field>
          <FieldLabel htmlFor="agent-active">Status</FieldLabel>
          <Select
            onValueChange={(value) => {
              onActiveChange(value === "false" ? "false" : "true")
            }}
            value={isActive}
          >
            <SelectTrigger className="w-full" id="agent-active">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="start">
              <SelectGroup>
                <SelectItem value="true">Active</SelectItem>
                <SelectItem value="false">Inactive</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
          <FieldDescription>
            Inactive agents cannot start new runs or receive delegated work. Existing history is
            kept.
          </FieldDescription>
        </Field>

        <Field>
          <FieldLabel htmlFor="agent-favorite">Favorite</FieldLabel>
          <Select
            onValueChange={(value) => {
              onFavoriteChange(value === "true" ? "true" : "false")
            }}
            value={isFavorite}
          >
            <SelectTrigger className="w-full" id="agent-favorite">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="start">
              <SelectGroup>
                <SelectItem value="false">No</SelectItem>
                <SelectItem value="true">Yes</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
          <FieldDescription>
            Favorites are an organizational shortcut that makes this agent easier to find.
          </FieldDescription>
        </Field>
      </FieldGroup>
    </FormSection>
  )
}
